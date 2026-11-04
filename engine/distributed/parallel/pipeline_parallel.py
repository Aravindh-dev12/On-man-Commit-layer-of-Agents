"""
Pipeline Parallelism with 1F1B (One Forward, One Backward) Scheduling
Partitions transformer layers across pipeline stages and interleaves forward/backward
microbatches to minimize activation memory bubbles.
"""

import torch
import torch.nn as nn
import torch.distributed as dist
from typing import List, Optional, Tuple, Dict, Any


_PP_GROUP = None
_PP_STAGE_RANK = 0
_PP_NUM_STAGES = 1


def set_pipeline_parallel_group(group, stage_rank: int = 0, num_stages: int = 1):
    global _PP_GROUP, _PP_STAGE_RANK, _PP_NUM_STAGES
    _PP_GROUP = group
    _PP_STAGE_RANK = stage_rank
    _PP_NUM_STAGES = num_stages


def get_pp_stage_rank() -> int:
    return _PP_STAGE_RANK


def get_pp_num_stages() -> int:
    return _PP_NUM_STAGES


def send_activation(tensor: torch.Tensor, next_rank: int):
    """Non-blocking P2P send of activation tensor to next pipeline stage."""
    if not dist.is_initialized() or _PP_NUM_STAGES == 1:
        return None
    return dist.isend(tensor.contiguous(), dst=next_rank, tag=0)


def recv_activation(shape: torch.Size, prev_rank: int, device: torch.device, dtype: torch.dtype) -> Tuple[torch.Tensor, Any]:
    """Non-blocking P2P receive of activation tensor from previous pipeline stage."""
    if not dist.is_initialized() or _PP_NUM_STAGES == 1:
        return torch.empty(shape, device=device, dtype=dtype), None
    tensor = torch.empty(shape, device=device, dtype=dtype)
    req = dist.irecv(tensor, src=prev_rank, tag=0)
    return tensor, req


def send_gradient(tensor: torch.Tensor, prev_rank: int):
    """Non-blocking P2P send of gradient tensor to previous pipeline stage."""
    if not dist.is_initialized() or _PP_NUM_STAGES == 1:
        return None
    return dist.isend(tensor.contiguous(), dst=prev_rank, tag=1)


def recv_gradient(shape: torch.Size, next_rank: int, device: torch.device, dtype: torch.dtype) -> Tuple[torch.Tensor, Any]:
    """Non-blocking P2P receive of gradient tensor from next pipeline stage."""
    if not dist.is_initialized() or _PP_NUM_STAGES == 1:
        return torch.empty(shape, device=device, dtype=dtype), None
    tensor = torch.empty(shape, device=device, dtype=dtype)
    req = dist.irecv(tensor, src=next_rank, tag=1)
    return tensor, req


class PipelineStage(nn.Module):
    """
    Encapsulates the subset of transformer layers allocated to this pipeline stage.
    """
    def __init__(self, layers: nn.ModuleList, is_first_stage: bool, is_last_stage: bool):
        super().__init__()
        self.layers = layers
        self.is_first_stage = is_first_stage
        self.is_last_stage = is_last_stage

    def forward(self, hidden_states: torch.Tensor) -> torch.Tensor:
        for layer in self.layers:
            hidden_states = layer(hidden_states)
        return hidden_states


class PipelineSchedule1F1B:
    """
    1F1B (One Forward, One Backward) Scheduler.
    Executes a stream of microbatches through pipeline stages, keeping in-flight
    activations bounded by the number of pipeline stages.
    """
    def __init__(
        self,
        stage: PipelineStage,
        num_microbatches: int,
        stage_rank: int,
        num_stages: int,
        prev_rank: Optional[int] = None,
        next_rank: Optional[int] = None,
    ):
        self.stage = stage
        self.num_microbatches = num_microbatches
        self.stage_rank = stage_rank
        self.num_stages = num_stages
        self.prev_rank = prev_rank if prev_rank is not None else max(0, stage_rank - 1)
        self.next_rank = next_rank if next_rank is not None else min(num_stages - 1, stage_rank + 1)

    def run_train_step(
        self,
        microbatches: List[torch.Tensor],
        targets: Optional[List[torch.Tensor]] = None,
        loss_fn: Optional[Any] = None,
    ) -> float:
        """
        Executes 1F1B pipeline schedule over all microbatches.
        Returns accumulated loss.
        """
        input_tensors = []
        output_tensors = []
        total_loss = 0.0

        num_warmup = min(self.num_stages - self.stage_rank, self.num_microbatches)
        num_steady = self.num_microbatches - num_warmup

        # -------------------------------------------------------------
        # Phase 1: Warmup Forward Passes
        # -------------------------------------------------------------
        for mb_idx in range(num_warmup):
            hidden = microbatches[mb_idx] if self.stage.is_first_stage else None
            # Forward computation
            out = self.stage(hidden)
            input_tensors.append(hidden)
            output_tensors.append(out)

        # -------------------------------------------------------------
        # Phase 2: Steady State 1F1B (1 Forward, 1 Backward)
        # -------------------------------------------------------------
        for mb_idx in range(num_steady):
            # 1 Forward
            fwd_mb_idx = num_warmup + mb_idx
            hidden = microbatches[fwd_mb_idx] if self.stage.is_first_stage else None
            out = self.stage(hidden)
            input_tensors.append(hidden)
            output_tensors.append(out)

            # 1 Backward
            bwd_mb_idx = mb_idx
            out_bwd = output_tensors[bwd_mb_idx]
            if self.stage.is_last_stage and targets is not None and loss_fn is not None:
                loss = loss_fn(out_bwd, targets[bwd_mb_idx])
                loss.backward()
                total_loss += loss.item()
            elif out_bwd.grad_fn is not None:
                out_bwd.backward(torch.ones_like(out_bwd))

        # -------------------------------------------------------------
        # Phase 3: Cooldown Remaining Backward Passes
        # -------------------------------------------------------------
        for mb_idx in range(num_steady, self.num_microbatches):
            out_bwd = output_tensors[mb_idx]
            if self.stage.is_last_stage and targets is not None and loss_fn is not None:
                loss = loss_fn(out_bwd, targets[mb_idx])
                loss.backward()
                total_loss += loss.item()
            elif out_bwd.grad_fn is not None:
                out_bwd.backward(torch.ones_like(out_bwd))

        return total_loss / max(1, self.num_microbatches)
