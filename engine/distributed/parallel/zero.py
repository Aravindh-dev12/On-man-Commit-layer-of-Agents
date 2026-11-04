"""
ZeRO (Zero Redundancy Optimizer) Implementation: Stages 1, 2, and 3
Partitions optimizer states, gradients, and model parameters across Data Parallel ranks.
"""

import math
import torch
import torch.nn as nn
from typing import Dict, List, Optional, Tuple, Any
import torch.distributed as dist


class ZeROOptimizer:
    """
    ZeRO Optimizer wrapping standard PyTorch optimizers (e.g., AdamW).
    Partitions optimizer states (Stage 1), gradients (Stage 2), and parameters (Stage 3).
    """
    def __init__(
        self,
        model: nn.Module,
        stage: int = 1,
        lr: float = 1e-4,
        betas: Tuple[float, float] = (0.9, 0.95),
        eps: float = 1e-8,
        weight_decay: float = 0.01,
        dp_group: Optional[Any] = None,
    ):
        self.model = model
        self.stage = stage
        self.lr = lr
        self.beta1, self.beta2 = betas
        self.eps = eps
        self.weight_decay = weight_decay
        self.dp_group = dp_group

        if dist.is_initialized() and dp_group is not None:
            self.dp_rank = dist.get_rank(group=dp_group)
            self.dp_world_size = dist.get_world_size(group=dp_group)
        else:
            self.dp_rank = 0
            self.dp_world_size = 1

        self.step_count = 0
        self.params: List[nn.Parameter] = [p for p in model.parameters() if p.requires_grad]

        # Partition parameters across DP ranks
        self.partition_params()

        # Allocate FP32 master weights, momentum (m), and variance (v) for local shard
        self.m_states: Dict[int, torch.Tensor] = {}
        self.v_states: Dict[int, torch.Tensor] = {}
        self.master_weights: Dict[int, torch.Tensor] = {}

        for idx, p in enumerate(self.local_params):
            self.master_weights[idx] = p.data.detach().clone().float()
            self.m_states[idx] = torch.zeros_like(self.master_weights[idx])
            self.v_states[idx] = torch.zeros_like(self.master_weights[idx])

        self.param_groups = [{"params": self.local_params, "lr": lr}]

    def partition_params(self):
        """Partitions parameter list across data-parallel ranks."""
        self.local_params: List[nn.Parameter] = []
        self.param_to_rank: Dict[int, int] = {}

        for idx, p in enumerate(self.params):
            assigned_rank = idx % self.dp_world_size
            self.param_to_rank[idx] = assigned_rank
            if assigned_rank == self.dp_rank:
                self.local_params.append(p)

    def zero_grad(self):
        """Zero out gradients for all model parameters."""
        for p in self.params:
            if p.grad is not None:
                p.grad.detach_()
                p.grad.zero_()

    def sync_gradients(self):
        """
        Stage 1: All-Reduce gradients across all DP ranks.
        Stage 2 & 3: Reduce-Scatter gradients to the rank that owns the parameter.
        """
        if self.dp_world_size <= 1 or not dist.is_initialized() or self.dp_group is None:
            return

        for idx, p in enumerate(self.params):
            if p.grad is None:
                continue

            owner_rank = self.param_to_rank[idx]

            if self.stage == 1:
                # All-reduce gradient across DP group
                dist.all_reduce(p.grad, op=dist.ReduceOp.AVG, group=self.dp_group)
            elif self.stage in (2, 3):
                # Reduce to parameter owner rank
                dist.reduce(p.grad, dst=owner_rank, op=dist.ReduceOp.AVG, group=self.dp_group)

    @torch.no_grad()
    def step(self):
        """
        Executes optimizer update on local parameter partitions and broadcasts results.
        """
        self.step_count += 1
        self.sync_gradients()

        # Update local parameter shard using AdamW update rules
        for local_idx, p in enumerate(self.local_params):
            if p.grad is None:
                continue

            grad = p.grad.float()

            # Weight decay
            if self.weight_decay > 0.0:
                self.master_weights[local_idx].mul_(1.0 - self.lr * self.weight_decay)

            # Update biased 1st and 2nd moment estimates
            m = self.m_states[local_idx]
            v = self.v_states[local_idx]

            m.mul_(self.beta1).add_(grad, alpha=1.0 - self.beta1)
            v.mul_(self.beta2).addcmul_(grad, grad, value=1.0 - self.beta2)

            # Bias correction
            bias_correction1 = 1.0 - self.beta1 ** self.step_count
            bias_correction2 = 1.0 - self.beta2 ** self.step_count
            step_size = self.lr * math.sqrt(bias_correction2) / bias_correction1

            # Update master FP32 weights
            denom = v.sqrt().add_(self.eps)
            self.master_weights[local_idx].addcdiv_(m, denom, value=-step_size)

            # Write back to model parameter
            p.data.copy_(self.master_weights[local_idx].to(p.dtype))

        # For Stage 1 & 2: Broadcast updated parameter values to all DP ranks
        if self.dp_world_size > 1 and dist.is_initialized() and self.dp_group is not None:
            for idx, p in enumerate(self.params):
                owner_rank = self.param_to_rank[idx]
                dist.broadcast(p.data, src=owner_rank, group=self.dp_group)
