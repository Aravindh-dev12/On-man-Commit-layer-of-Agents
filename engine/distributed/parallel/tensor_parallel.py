"""
Megatron-LM Style Tensor Parallelism Modules
Splits attention heads and MLP intermediate dimensions across GPUs in the Tensor Parallel (TP) group.
"""

import math
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.distributed as dist
from typing import Optional, Tuple

from engine.cuda.ops import onman_flash_attention


# Global Process Group references for Tensor Parallelism
_TP_GROUP = None
_TP_WORLD_SIZE = 1
_TP_RANK = 0


def set_tensor_parallel_group(group, rank: int = 0, world_size: int = 1):
    global _TP_GROUP, _TP_RANK, _TP_WORLD_SIZE
    _TP_GROUP = group
    _TP_RANK = rank
    _TP_WORLD_SIZE = world_size


def get_tp_group():
    return _TP_GROUP


def get_tp_world_size() -> int:
    return _TP_WORLD_SIZE


def get_tp_rank() -> int:
    return _TP_RANK


# =========================================================================
# Distributed Autograd Communication Functions
# =========================================================================

class _CopyToModelParallelRegion(torch.autograd.Function):
    """Pass input through on forward, all-reduce gradients on backward."""
    @staticmethod
    def forward(ctx, input_):
        return input_

    @staticmethod
    def backward(ctx, grad_output):
        if _TP_WORLD_SIZE == 1 or not dist.is_initialized() or _TP_GROUP is None:
            return grad_output
        dist.all_reduce(grad_output, op=dist.ReduceOp.SUM, group=_TP_GROUP)
        return grad_output


class _ReduceFromModelParallelRegion(torch.autograd.Function):
    """All-reduce activations on forward, pass gradients through on backward."""
    @staticmethod
    def forward(ctx, input_):
        if _TP_WORLD_SIZE == 1 or not dist.is_initialized() or _TP_GROUP is None:
            return input_
        dist.all_reduce(input_, op=dist.ReduceOp.SUM, group=_TP_GROUP)
        return input_

    @staticmethod
    def backward(ctx, grad_output):
        return grad_output


class _ScatterToModelParallelRegion(torch.autograd.Function):
    """Split input along last dimension across TP ranks."""
    @staticmethod
    def forward(ctx, input_):
        if _TP_WORLD_SIZE == 1:
            return input_
        dim_size = input_.size(-1) // _TP_WORLD_SIZE
        start = _TP_RANK * dim_size
        end = start + dim_size
        return input_[..., start:end].contiguous()

    @staticmethod
    def backward(ctx, grad_output):
        if _TP_WORLD_SIZE == 1 or not dist.is_initialized() or _TP_GROUP is None:
            return grad_output
        # All-gather gradients on backward
        tensor_list = [torch.empty_like(grad_output) for _ in range(_TP_WORLD_SIZE)]
        dist.all_gather(tensor_list, grad_output, group=_TP_GROUP)
        return torch.cat(tensor_list, dim=-1).contiguous()


# =========================================================================
# Parallel Linear Layers
# =========================================================================

class ColumnParallelLinear(nn.Module):
    """
    Linear layer where the weight matrix is partitioned along the column (output) dimension:
    W = [W_1, W_2, ..., W_tp]
    Output Y_i = X @ W_i.
    Gradients are all-reduced on backward.
    """
    def __init__(self, in_features: int, out_features: int, bias: bool = False, gather_output: bool = False):
        super().__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.gather_output = gather_output

        tp_size = get_tp_world_size()
        assert out_features % tp_size == 0, f"out_features {out_features} must be divisible by tp_size {tp_size}"
        self.split_out_features = out_features // tp_size

        # Weight shape: [split_out_features, in_features]
        self.weight = nn.Parameter(torch.empty(self.split_out_features, in_features))
        if bias:
            self.bias = nn.Parameter(torch.empty(self.split_out_features))
        else:
            self.register_parameter("bias", None)

        self.reset_parameters()

    def reset_parameters(self):
        nn.init.kaiming_uniform_(self.weight, a=math.sqrt(5))
        if self.bias is not None:
            fan_in, _ = nn.init._calculate_fan_in_and_fan_out(self.weight)
            bound = 1 / math.sqrt(fan_in) if fan_in > 0 else 0
            nn.init.uniform_(self.bias, -bound, bound)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        input_parallel = _CopyToModelParallelRegion.apply(x)
        output_parallel = F.linear(input_parallel, self.weight, self.bias)
        if self.gather_output and get_tp_world_size() > 1 and dist.is_initialized() and _TP_GROUP is not None:
            tensor_list = [torch.empty_like(output_parallel) for _ in range(_TP_WORLD_SIZE)]
            dist.all_gather(tensor_list, output_parallel, group=_TP_GROUP)
            return torch.cat(tensor_list, dim=-1).contiguous()
        return output_parallel


class RowParallelLinear(nn.Module):
    """
    Linear layer where the weight matrix is partitioned along the row (input) dimension:
    W = [W_1; W_2; ...; W_tp]
    Input X is split: X = [X_1, X_2, ..., X_tp]
    Local Output Y_i = X_i @ W_i.
    Final output is all-reduced across TP ranks: Y = sum(Y_i).
    """
    def __init__(self, in_features: int, out_features: int, bias: bool = False, input_is_parallel: bool = True):
        super().__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.input_is_parallel = input_is_parallel

        tp_size = get_tp_world_size()
        assert in_features % tp_size == 0, f"in_features {in_features} must be divisible by tp_size {tp_size}"
        self.split_in_features = in_features // tp_size

        # Weight shape: [out_features, split_in_features]
        self.weight = nn.Parameter(torch.empty(out_features, self.split_in_features))
        if bias:
            self.bias = nn.Parameter(torch.empty(out_features))
        else:
            self.register_parameter("bias", None)

        self.reset_parameters()

    def reset_parameters(self):
        nn.init.kaiming_uniform_(self.weight, a=math.sqrt(5))
        if self.bias is not None:
            fan_in, _ = nn.init._calculate_fan_in_and_fan_out(self.weight)
            bound = 1 / math.sqrt(fan_in) if fan_in > 0 else 0
            nn.init.uniform_(self.bias, -bound, bound)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if not self.input_is_parallel:
            x = _ScatterToModelParallelRegion.apply(x)
        output_parallel = F.linear(x, self.weight)
        output_ = _ReduceFromModelParallelRegion.apply(output_parallel)
        if self.bias is not None:
            output_ = output_ + self.bias
        return output_


# =========================================================================
# Parallel Attention with Custom CUDA FlashAttention
# =========================================================================

class ParallelAttention(nn.Module):
    """
    Tensor-Parallel Multi-Head Attention.
    Splits attention heads across GPUs: each GPU holds (H / TP) heads.
    Uses Onman CUDA FlashAttention kernel locally on each GPU without cross-GPU communication.
    Communicates via All-Reduce only on the output projection!
    """
    def __init__(self, hidden_size: int, num_heads: int, is_causal: bool = True):
        super().__init__()
        self.hidden_size = hidden_size
        self.num_heads = num_heads
        self.head_dim = hidden_size // num_heads
        self.is_causal = is_causal

        tp_size = get_tp_world_size()
        assert num_heads % tp_size == 0, f"num_heads {num_heads} must be divisible by tp_size {tp_size}"
        self.num_local_heads = num_heads // tp_size

        # QKV projected with Column-Parallel Linear (produces 3 * local_hidden_size)
        self.qkv_proj = ColumnParallelLinear(hidden_size, 3 * hidden_size, bias=False, gather_output=False)
        # Output projected with Row-Parallel Linear (All-Reduces to full hidden_size)
        self.out_proj = RowParallelLinear(hidden_size, hidden_size, bias=False, input_is_parallel=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, N, C = x.shape

        # [B, N, C] -> [B, N, 3 * local_heads * head_dim]
        qkv = self.qkv_proj(x)
        qkv = qkv.reshape(B, N, 3, self.num_local_heads, self.head_dim)
        q, k, v = qkv.unbind(dim=2)

        # Transpose to [B, local_heads, N, D]
        q = q.transpose(1, 2).contiguous()
        k = k.transpose(1, 2).contiguous()
        v = v.transpose(1, 2).contiguous()

        # Execute Onman CUDA FlashAttention kernel locally on this GPU's subset of heads!
        local_context = onman_flash_attention(q, k, v, is_causal=self.is_causal)

        # Reshape to [B, N, local_heads * head_dim]
        local_context = local_context.transpose(1, 2).contiguous().reshape(B, N, self.num_local_heads * self.head_dim)

        # Row-Parallel Out projection with All-Reduce across TP group
        return self.out_proj(local_context)


# =========================================================================
# Parallel MLP (SwiGLU)
# =========================================================================

class ParallelMLP(nn.Module):
    """
    Tensor-Parallel SwiGLU MLP.
    Gate & Up projection: ColumnParallelLinear
    Down projection: RowParallelLinear (with All-Reduce)
    """
    def __init__(self, hidden_size: int, intermediate_size: int):
        super().__init__()
        # ColumnParallel up-projection
        self.gate_up_proj = ColumnParallelLinear(hidden_size, 2 * intermediate_size, bias=False)
        # RowParallel down-projection
        self.down_proj = RowParallelLinear(intermediate_size, hidden_size, bias=False, input_is_parallel=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # [B, N, 2 * split_intermediate]
        gate_up = self.gate_up_proj(x)
        gate, up = gate_up.chunk(2, dim=-1)
        hidden = F.silu(gate) * up
        return self.down_proj(hidden)
