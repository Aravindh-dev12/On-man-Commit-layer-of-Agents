"""
Benchmark comparing Onman FlashAttention vs Standard Quadratic Attention.
Measures execution latency (ms), peak GPU memory (MB), and effective TFLOPS.
"""

import os
import sys
import time
import torch
import torch.nn.functional as F

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from engine.cuda.ops import onman_flash_attention


def benchmark_attention(
    batch_size: int = 2,
    num_heads: int = 8,
    seq_len: int = 2048,
    head_dim: int = 64,
    is_causal: bool = True,
    warmup: int = 10,
    iters: int = 50,
    device: str = "cuda" if torch.cuda.is_available() else "cpu",
):
    print(f"\n=======================================================")
    print(f"Attention Benchmark: B={batch_size}, H={num_heads}, N={seq_len}, D={head_dim}, Causal={is_causal}")
    print(f"Device: {device.upper()}")
    print(f"=======================================================")

    q = torch.randn(batch_size, num_heads, seq_len, head_dim, device=device, dtype=torch.float32, requires_grad=True)
    k = torch.randn(batch_size, num_heads, seq_len, head_dim, device=device, dtype=torch.float32, requires_grad=True)
    v = torch.randn(batch_size, num_heads, seq_len, head_dim, device=device, dtype=torch.float32, requires_grad=True)

    # Theoretical FLOPs: 2 * B * H * N * N * D (causal) or 4 * B * H * N * N * D (non-causal)
    flops_per_iter = (2.0 if is_causal else 4.0) * batch_size * num_heads * (seq_len ** 2) * head_dim

    # 1. Benchmark Standard Materialized Attention: Softmax(Q @ K^T) @ V
    # Warmup
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()

    start_mem_std = torch.cuda.memory_allocated() if device == "cuda" else 0

    for _ in range(warmup):
        out_std = F.scaled_dot_product_attention(q, k, v, is_causal=is_causal)
        if device == "cuda":
            torch.cuda.synchronize()

    t0 = time.perf_counter()
    for _ in range(iters):
        out_std = F.scaled_dot_product_attention(q, k, v, is_causal=is_causal)
        if device == "cuda":
            torch.cuda.synchronize()
    t1 = time.perf_counter()

    time_std_ms = ((t1 - t0) / iters) * 1000.0
    tflops_std = (flops_per_iter / (time_std_ms / 1000.0)) / 1e12
    peak_mem_std = (torch.cuda.max_memory_allocated() - start_mem_std) / (1024 * 1024) if device == "cuda" else 0.0

    # 2. Benchmark Onman FlashAttention
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()

    start_mem_flash = torch.cuda.memory_allocated() if device == "cuda" else 0

    for _ in range(warmup):
        out_flash = onman_flash_attention(q, k, v, is_causal=is_causal)
        if device == "cuda":
            torch.cuda.synchronize()

    t0 = time.perf_counter()
    for _ in range(iters):
        out_flash = onman_flash_attention(q, k, v, is_causal=is_causal)
        if device == "cuda":
            torch.cuda.synchronize()
    t1 = time.perf_counter()

    time_flash_ms = ((t1 - t0) / iters) * 1000.0
    tflops_flash = (flops_per_iter / (time_flash_ms / 1000.0)) / 1e12
    peak_mem_flash = (torch.cuda.max_memory_allocated() - start_mem_flash) / (1024 * 1024) if device == "cuda" else 0.0

    print(f"Standard Attention : {time_std_ms:7.2f} ms | {tflops_std:6.2f} TFLOPS | Memory: {peak_mem_std:6.1f} MB")
    print(f"Onman FlashAttention: {time_flash_ms:7.2f} ms | {tflops_flash:6.2f} TFLOPS | Memory: {peak_mem_flash:6.1f} MB")
    if peak_mem_std > 0 and peak_mem_flash > 0:
        print(f"Memory Reduction    : {peak_mem_std / max(peak_mem_flash, 0.01):.1f}x lower HBM footprint")
    print(f"Max numerical diff  : {(out_std - out_flash).abs().max().item():.2e}")


if __name__ == "__main__":
    benchmark_attention(batch_size=2, num_heads=4, seq_len=512, head_dim=64, iters=20)
