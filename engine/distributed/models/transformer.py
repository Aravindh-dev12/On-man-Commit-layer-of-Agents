"""
Distributed Transformer Language Model
Integrated with Onman CUDA FlashAttention, Megatron Tensor Parallelism,
Rotary Position Embeddings (RoPE), and RMSNorm.
"""

import math
import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Optional, Tuple

from engine.distributed.config import DistributedModelConfig
from engine.distributed.parallel.tensor_parallel import (
    ParallelAttention,
    ParallelMLP,
    ColumnParallelLinear,
    get_tp_world_size,
)


class RMSNorm(nn.Module):
    """Root Mean Square Layer Normalization (Llama/Mistral style)."""
    def __init__(self, dim: int, eps: float = 1e-6):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        variance = x.pow(2).mean(-1, keepdim=True)
        return x * torch.rsqrt(variance + self.eps) * self.weight


class RotaryEmbedding(nn.Module):
    """Rotary Position Embedding (RoPE) for relative position awareness."""
    def __init__(self, dim: int, max_seq_len: int = 2048, theta: float = 10000.0):
        super().__init__()
        self.dim = dim
        self.max_seq_len = max_seq_len
        self.theta = theta

        inv_freq = 1.0 / (theta ** (torch.arange(0, dim, 2).float() / dim))
        self.register_buffer("inv_freq", inv_freq, persistent=False)
        self._build_cache(max_seq_len)

    def _build_cache(self, seq_len: int):
        t = torch.arange(seq_len, dtype=torch.float32, device=self.inv_freq.device)
        freqs = torch.outer(t, self.inv_freq)
        emb = torch.cat((freqs, freqs), dim=-1)
        self.register_buffer("cos_cached", emb.cos(), persistent=False)
        self.register_buffer("sin_cached", emb.sin(), persistent=False)

    def forward(self, x: torch.Tensor, seq_len: int) -> Tuple[torch.Tensor, torch.Tensor]:
        if seq_len > self.cos_cached.size(0):
            self._build_cache(seq_len)
        return self.cos_cached[:seq_len], self.sin_cached[:seq_len]


def apply_rotary_pos_emb(x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    """Rotate half of the hidden dimension by sinusoidal frequencies."""
    # x: [B, H, N, D]
    d_half = x.shape[-1] // 2
    x1 = x[..., :d_half]
    x2 = x[..., d_half:]
    rotated_x = torch.cat((-x2, x1), dim=-1)
    cos = cos[None, None, :x.shape[2], :]
    sin = sin[None, None, :x.shape[2], :]
    return (x * cos) + (rotated_x * sin)


class TransformerBlock(nn.Module):
    """
    Standard Transformer Decoder Layer equipped with:
    - Pre-norm RMSNorm
    - Tensor-Parallel Attention with Onman CUDA FlashAttention
    - Pre-MLP RMSNorm
    - Tensor-Parallel SwiGLU MLP
    """
    def __init__(self, config: DistributedModelConfig):
        super().__init__()
        self.attn_norm = RMSNorm(config.hidden_size, eps=config.norm_eps)
        self.attn = ParallelAttention(
            hidden_size=config.hidden_size,
            num_heads=config.num_heads,
            is_causal=True,
        )

        self.mlp_norm = RMSNorm(config.hidden_size, eps=config.norm_eps)
        self.mlp = ParallelMLP(
            hidden_size=config.hidden_size,
            intermediate_size=config.intermediate_size,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Pre-norm Self-Attention with residual connection
        normed_attn_in = self.attn_norm(x)
        attn_out = self.attn(normed_attn_in)
        h = x + attn_out

        # Pre-norm Feed-Forward with residual connection
        normed_mlp_in = self.mlp_norm(h)
        mlp_out = self.mlp(normed_mlp_in)
        out = h + mlp_out
        return out


class DistributedTransformerLM(nn.Module):
    """
    Full Distributed Language Model.
    Supports Tensor Parallelism across GPUs and integrates custom CUDA Attention.
    """
    def __init__(self, config: DistributedModelConfig):
        super().__init__()
        self.config = config

        self.embed_tokens = nn.Embedding(config.vocab_size, config.hidden_size)
        self.layers = nn.ModuleList([
            TransformerBlock(config) for _ in range(config.num_layers)
        ])
        self.norm = RMSNorm(config.hidden_size, eps=config.norm_eps)

        if config.tie_word_embeddings:
            self.lm_head = None
        else:
            self.lm_head = ColumnParallelLinear(config.hidden_size, config.vocab_size, bias=False, gather_output=True)

        self.apply(self._init_weights)

    def _init_weights(self, module):
        if isinstance(module, (nn.Linear, ColumnParallelLinear)):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)
            if getattr(module, "bias", None) is not None and module.bias is not None:
                nn.init.zeros_(module.bias)
        elif isinstance(module, nn.Embedding):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def forward(
        self,
        input_ids: torch.Tensor,
        labels: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """
        Forward pass computing next-token logits and cross-entropy loss.
        """
        # [B, N] -> [B, N, C]
        h = self.embed_tokens(input_ids)

        for layer in self.layers:
            h = layer(h)

        h = self.norm(h)

        if self.lm_head is not None:
            logits = self.lm_head(h)
        else:
            logits = F.linear(h, self.embed_tokens.weight)

        loss = None
        if labels is not None:
            # Shift tokens for autoregressive language modeling:
            # predict token at index t+1 from tokens at 0..t
            shift_logits = logits[..., :-1, :].contiguous()
            shift_labels = labels[..., 1:].contiguous()
            loss = F.cross_entropy(
                shift_logits.view(-1, self.config.vocab_size),
                shift_labels.view(-1),
                ignore_index=-100,
            )

        return logits, loss
