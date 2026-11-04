---
name: onman-train
description: Launch, monitor, and profile distributed LLM training across multiple GPUs with 3D parallelism (TP/PP/DP + ZeRO) and high-performance CUDA FlashAttention.
---

# Onman Distributed Training & CUDA Attention

When user asks to train models, scale across GPUs, or benchmark FlashAttention kernels:

## 1. Quick CLI Commands

```bash
# Benchmark CUDA FlashAttention vs standard attention
python engine/cuda/benchmark.py

# Launch single-node distributed training test
python engine/distributed/train.py --steps 50 --hidden_size 512

# Multi-GPU training with Tensor Parallelism & ZeRO
torchrun --nproc_per_node=2 engine/distributed/train.py --tp_size 2 --zero_stage 1
```

## 2. Key Architecture

- **CUDA FlashAttention Kernel** (`engine/cuda/`): IO-aware tiled attention in SRAM with online softmax. $O(N)$ HBM memory instead of $O(N^2)$.
- **Tensor Parallelism** (`engine/distributed/parallel/tensor_parallel.py`): Splits attention heads across GPUs. FlashAttention executes locally on each rank.
- **Pipeline Parallelism** (`engine/distributed/parallel/pipeline_parallel.py`): 1F1B schedule across stages.
- **ZeRO Optimizer** (`engine/distributed/parallel/zero.py`): Partitions Adam states (Stage 1), gradients (Stage 2), and parameters (Stage 3).
