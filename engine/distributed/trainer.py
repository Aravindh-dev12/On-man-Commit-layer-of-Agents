"""
Distributed LLM Trainer
Manages 3D Parallelism (Data, Tensor, Pipeline), ZeRO Optimizer,
Mixed Precision (FP16/BF16), Gradient Accumulation, and Distributed Checkpointing.
"""

import os
import time
import math
import torch
import torch.nn as nn
import torch.distributed as dist
from typing import Optional, Dict, Any

from engine.distributed.config import DistributedModelConfig, ParallelTopologyConfig, TrainingConfig
from engine.distributed.models.transformer import DistributedTransformerLM
from engine.distributed.parallel.tensor_parallel import set_tensor_parallel_group
from engine.distributed.parallel.pipeline_parallel import set_pipeline_parallel_group
from engine.distributed.parallel.zero import ZeROOptimizer


class DistributedTrainer:
    """
    End-to-end distributed trainer orchestrating model parallelism and data parallelism.
    """
    def __init__(
        self,
        model_config: DistributedModelConfig,
        topo_config: ParallelTopologyConfig,
        train_config: TrainingConfig,
    ):
        self.model_config = model_config
        self.topo_config = topo_config
        self.train_config = train_config

        self.setup_distributed_environment()

        # Build Model
        self.model = DistributedTransformerLM(model_config).to(self.device)

        # Build Optimizer
        if self.topo_config.zero_stage > 0:
            self.optimizer = ZeROOptimizer(
                self.model,
                stage=self.topo_config.zero_stage,
                lr=self.train_config.learning_rate,
                weight_decay=self.train_config.weight_decay,
                dp_group=self.dp_group,
            )
        else:
            self.optimizer = torch.optim.AdamW(
                self.model.parameters(),
                lr=self.train_config.learning_rate,
                weight_decay=self.train_config.weight_decay,
            )

        # Mixed precision GradScaler
        self.scaler = torch.amp.GradScaler('cuda', enabled=(self.train_config.fp16 and self.device.type == "cuda"))

        self.global_step = 0

    def setup_distributed_environment(self):
        """Initializes 3D parallel process groups (TP, PP, DP)."""
        if dist.is_initialized():
            self.rank = dist.get_rank()
            self.world_size = dist.get_world_size()
        else:
            self.rank = int(os.environ.get("RANK", 0))
            self.world_size = int(os.environ.get("WORLD_SIZE", 1))

        self.local_rank = int(os.environ.get("LOCAL_RANK", 0))
        if torch.cuda.is_available():
            self.device = torch.device(f"cuda:{self.local_rank}")
            torch.cuda.set_device(self.device)
        else:
            self.device = torch.device("cpu")

        tp = self.topo_config.tp_size
        pp = self.topo_config.pp_size
        dp = self.topo_config.dp_size

        if tp * pp * dp != self.world_size:
            # Auto-adjust DP size to fit world size
            dp = max(1, self.world_size // (tp * pp))
            self.topo_config.dp_size = dp

        # Sub-process groups
        self.tp_group = None
        self.dp_group = None
        self.pp_group = None

        if dist.is_initialized() and self.world_size > 1:
            # Initialize 3D grid
            for p in range(pp):
                for d in range(dp):
                    # TP groups: consecutive ranks along TP dimension
                    tp_ranks = [p * (dp * tp) + d * tp + t for t in range(tp)]
                    group = dist.new_group(tp_ranks)
                    if self.rank in tp_ranks:
                        self.tp_group = group
                        set_tensor_parallel_group(group, rank=tp_ranks.index(self.rank), world_size=tp)

            for p in range(pp):
                for t in range(tp):
                    # DP groups: ranks along DP dimension
                    dp_ranks = [p * (dp * tp) + d * tp + t for d in range(dp)]
                    group = dist.new_group(dp_ranks)
                    if self.rank in dp_ranks:
                        self.dp_group = group

        else:
            set_tensor_parallel_group(None, rank=0, world_size=1)
            set_pipeline_parallel_group(None, stage_rank=0, num_stages=1)

    def get_learning_rate(self, step: int) -> float:
        """Cosine annealing schedule with linear warmup."""
        warmup = self.train_config.warmup_steps
        max_steps = self.train_config.max_steps
        lr = self.train_config.learning_rate
        min_lr = self.train_config.min_learning_rate

        if step < warmup:
            return lr * float(step) / float(max(1, warmup))
        if step > max_steps:
            return min_lr
        progress = float(step - warmup) / float(max(1, max_steps - warmup))
        return min_lr + 0.5 * (lr - min_lr) * (1.0 + math.cos(math.pi * progress))

    def train_step(self, input_ids: torch.Tensor, labels: torch.Tensor) -> Dict[str, float]:
        """Performs a single distributed training step with gradient accumulation."""
        self.model.train()
        self.optimizer.zero_grad()

        input_ids = input_ids.to(self.device)
        labels = labels.to(self.device)

        batch_size = input_ids.size(0)
        micro_bs = self.train_config.micro_batch_size
        num_microbatches = max(1, batch_size // micro_bs)

        total_loss = 0.0
        start_time = time.perf_counter()

        # Update learning rate
        current_lr = self.get_learning_rate(self.global_step)
        for param_group in getattr(self.optimizer, "param_groups", []):
            param_group["lr"] = current_lr
        if hasattr(self.optimizer, "lr"):
            self.optimizer.lr = current_lr

        # Micro-batch accumulation loop
        for mb_idx in range(num_microbatches):
            mb_input = input_ids[mb_idx * micro_bs : (mb_idx + 1) * micro_bs]
            mb_labels = labels[mb_idx * micro_bs : (mb_idx + 1) * micro_bs]

            with torch.amp.autocast(device_type=self.device.type, enabled=self.train_config.fp16):
                logits, loss = self.model(mb_input, labels=mb_labels)
                scaled_loss = loss / num_microbatches

            self.scaler.scale(scaled_loss).backward()
            total_loss += loss.item() / num_microbatches

        # Gradient clipping & Optimizer Step
        self.scaler.unscale_(self.optimizer)
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.train_config.max_grad_norm)

        if hasattr(self.optimizer, "local_params"):
            self.optimizer.step()
            self.scaler.update()
        else:
            self.scaler.step(self.optimizer)
            self.scaler.update()

        step_time = time.perf_counter() - start_time
        tokens_processed = batch_size * input_ids.size(1)
        tokens_per_sec = tokens_processed / max(step_time, 1e-5)

        self.global_step += 1

        return {
            "loss": total_loss,
            "lr": current_lr,
            "step_time_ms": step_time * 1000.0,
            "tokens_per_sec": tokens_per_sec,
            "global_step": self.global_step,
        }

    def save_checkpoint(self, path: str):
        """Saves distributed model checkpoint."""
        if self.rank == 0:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            checkpoint = {
                "step": self.global_step,
                "model_state": self.model.state_dict(),
                "config": self.model_config,
            }
            torch.save(checkpoint, path)
            print(f"[Rank {self.rank}] Checkpoint saved to {path}")
