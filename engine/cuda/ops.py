"""
Onman CUDA Attention Python Interface & Reference Engine
Implements the IO-Aware Tiled FlashAttention algorithm with online softmax.
"""

import math
import torch
import torch.nn as nn
from typing import Optional, Tuple

# Try importing compiled C++/CUDA extension if installed
_compiled_extension = None
try:
    import onman_cuda_attention as _compiled_extension
except ImportError:
    _compiled_extension = None


def tiled_flash_attention_reference(
    q: torch.Tensor,
    k: torch.Tensor,
    v: torch.Tensor,
    is_causal: bool = True,
    scale: Optional[float] = None,
    block_r: int = 64,
    block_c: int = 64,
) -> Tuple[torch.Tensor, torch.Tensor]:
    """
    Exact mathematical reference of the FlashAttention-2 algorithm with online softmax.
    Computes Attention(Q, K, V) by tiling SRAM blocks without materializing
    the full [Batch, Heads, SeqLen, SeqLen] attention matrix in memory.

    Args:
        q: [B, H, N_q, D]
        k: [B, H, N_k, D]
        v: [B, H, N_k, D]
        is_causal: apply lower-triangular causal mask
        scale: softmax temperature factor (default 1 / sqrt(D))
        block_r: tile size for queries (Br)
        block_c: tile size for keys/values (Bc)

    Returns:
        output: [B, H, N_q, D]
        logsumexp: [B, H, N_q]
    """
    B, H, N_q, D = q.shape
    _, _, N_k, _ = k.shape
    scale = scale or (1.0 / math.sqrt(D))

    output = torch.zeros_like(q)
    logsumexp = torch.zeros(B, H, N_q, device=q.device, dtype=torch.float32)

    num_q_blocks = math.ceil(N_q / block_r)
    num_k_blocks = math.ceil(N_k / block_c)

    for i in range(num_q_blocks):
        q_start = i * block_r
        q_end = min((i + 1) * block_r, N_q)
        q_tile = q[:, :, q_start:q_end, :] * scale  # [B, H, Br, D]
        actual_br = q_end - q_start

        # State accumulators for this Q tile in local memory
        m_prev = torch.full((B, H, actual_br, 1), -float("inf"), device=q.device, dtype=torch.float32)
        l_prev = torch.zeros((B, H, actual_br, 1), device=q.device, dtype=torch.float32)
        o_acc = torch.zeros((B, H, actual_br, D), device=q.device, dtype=torch.float32)

        max_k_block = num_k_blocks
        if is_causal:
            max_k_block = min(num_k_blocks, math.ceil(q_end / block_c))

        for j in range(max_k_block):
            k_start = j * block_c
            k_end = min((j + 1) * block_c, N_k)
            k_tile = k[:, :, k_start:k_end, :]  # [B, H, Bc, D]
            v_tile = v[:, :, k_start:k_end, :]  # [B, H, Bc, D]
            actual_bc = k_end - k_start

            # Compute S_ij = Q_tile @ K_tile^T
            # [B, H, Br, D] x [B, H, D, Bc] -> [B, H, Br, Bc]
            s_tile = torch.matmul(q_tile.float(), k_tile.float().transpose(-1, -2))

            if is_causal:
                # Causal row-col coordinate mask
                q_coords = torch.arange(q_start, q_end, device=q.device)[:, None]
                k_coords = torch.arange(k_start, k_end, device=q.device)[None, :]
                causal_mask = q_coords < k_coords
                s_tile = s_tile.masked_fill(causal_mask[None, None, :, :], -float("inf"))

            # Online Softmax step
            tile_max = torch.max(s_tile, dim=-1, keepdim=True).values  # [B, H, Br, 1]
            m_curr = torch.maximum(m_prev, tile_max)
            scale_prev = torch.exp(m_prev - m_curr)
            scale_prev = torch.nan_to_num(scale_prev, 0.0)

            # Softmax numerator for this tile: P_tile = exp(S_tile - m_curr)
            p_tile = torch.exp(s_tile - m_curr)
            p_tile = torch.nan_to_num(p_tile, 0.0)
            sum_p = torch.sum(p_tile, dim=-1, keepdim=True)  # [B, H, Br, 1]

            # Rescale existing accumulator and add P_tile @ V_tile
            o_acc = o_acc * scale_prev + torch.matmul(p_tile, v_tile.float())

            # Update running statistics
            l_prev = l_prev * scale_prev + sum_p
            m_prev = m_curr

        # Normalize output by total denominator sum: O_i = O_acc / l_i
        inv_l = torch.where(l_prev > 0, 1.0 / l_prev, torch.zeros_like(l_prev))
        normalized_o = (o_acc * inv_l).to(q.dtype)
        output[:, :, q_start:q_end, :] = normalized_o

        # LogSumExp L = m + log(l)
        l_log = m_prev.squeeze(-1) + torch.log(torch.clamp(l_prev.squeeze(-1), min=1e-8))
        logsumexp[:, :, q_start:q_end] = l_log

    return output, logsumexp


class FlashAttentionFunction(torch.autograd.Function):
    """
    Differentiable PyTorch Autograd Function for Onman FlashAttention.
    Delegates to the compiled CUDA kernel when available and on CUDA,
    otherwise executes the exact tiled online softmax reference.
    """

    @staticmethod
    def forward(
        ctx,
        q: torch.Tensor,
        k: torch.Tensor,
        v: torch.Tensor,
        is_causal: bool = True,
        scale: Optional[float] = None,
    ) -> torch.Tensor:
        D = q.size(-1)
        scale = scale or (1.0 / math.sqrt(D))

        if _compiled_extension is not None and q.is_cuda and D == 64 and q.dtype == torch.float32:
            out, l = _compiled_extension.forward(q.contiguous(), k.contiguous(), v.contiguous(), is_causal, scale)
        else:
            out, l = tiled_flash_attention_reference(q, k, v, is_causal=is_causal, scale=scale)

        ctx.save_for_backward(q, k, v, out, l)
        ctx.is_causal = is_causal
        ctx.scale = scale
        return out

    @staticmethod
    def backward(ctx, d_out: torch.Tensor):
        q, k, v, out, l = ctx.saved_tensors
        is_causal = ctx.is_causal
        scale = ctx.scale

        if _compiled_extension is not None and q.is_cuda and q.size(-1) == 64 and q.dtype == torch.float32:
            dq, dk, dv = _compiled_extension.backward(
                d_out.contiguous(), q.contiguous(), k.contiguous(), v.contiguous(), out.contiguous(), l.contiguous(), is_causal, scale
            )
            return dq, dk, dv, None, None

        # Reference autograd backward pass using recomputed attention
        # P = softmax(Q K^T * scale) = exp(Q K^T * scale - L)
        scores = torch.matmul(q.float(), k.float().transpose(-1, -2)) * scale
        if is_causal:
            N_q, N_k = q.size(2), k.size(2)
            causal_mask = torch.triu(torch.ones(N_q, N_k, device=q.device, dtype=torch.bool), diagonal=1)
            scores = scores.masked_fill(causal_mask[None, None, :, :], -float("inf"))

        p = torch.softmax(scores, dim=-1)
        dv = torch.matmul(p.transpose(-1, -2), d_out.float()).to(v.dtype)

        dp = torch.matmul(d_out.float(), v.float().transpose(-1, -2))
        d_scores = p * (dp - (d_out.float() * out.float()).sum(dim=-1, keepdim=True)) * scale
        dq = torch.matmul(d_scores, k.float()).to(q.dtype)
        dk = torch.matmul(d_scores.transpose(-1, -2), q.float()).to(k.dtype)

        return dq, dk, dv, None, None


def onman_flash_attention(
    q: torch.Tensor,
    k: torch.Tensor,
    v: torch.Tensor,
    is_causal: bool = True,
    scale: Optional[float] = None,
) -> torch.Tensor:
    """
    User-facing high-performance attention function.
    """
    return FlashAttentionFunction.apply(q, k, v, is_causal, scale)


class FlashAttentionLayer(nn.Module):
    """
    Ready-to-use PyTorch Multi-Head Attention module powered by Onman CUDA FlashAttention.
    """

    def __init__(
        self,
        hidden_size: int,
        num_heads: int,
        is_causal: bool = True,
        dropout: float = 0.0,
    ):
        super().__init__()
        assert hidden_size % num_heads == 0, "hidden_size must be divisible by num_heads"
        self.hidden_size = hidden_size
        self.num_heads = num_heads
        self.head_dim = hidden_size // num_heads
        self.is_causal = is_causal
        self.scale = 1.0 / math.sqrt(self.head_dim)

        self.qkv_proj = nn.Linear(hidden_size, 3 * hidden_size, bias=False)
        self.out_proj = nn.Linear(hidden_size, hidden_size, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, N, C = x.shape
        qkv = self.qkv_proj(x).reshape(B, N, 3, self.num_heads, self.head_dim)
        # Permute to [B, H, N, D]
        q, k, v = qkv.unbind(dim=2)
        q = q.transpose(1, 2)
        k = k.transpose(1, 2)
        v = v.transpose(1, 2)

        out = onman_flash_attention(q, k, v, is_causal=self.is_causal, scale=self.scale)

        # [B, H, N, D] -> [B, N, H * D]
        out = out.transpose(1, 2).reshape(B, N, C)
        return self.out_proj(out)
