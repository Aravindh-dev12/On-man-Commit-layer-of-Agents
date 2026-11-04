# Onman Distributed LLM Training System

High-efficiency, 3D-parallel distributed training engine designed to scale Large Language Models across multiple GPUs and nodes. Incorporates Megatron Tensor Parallelism, 1F1B Pipeline Parallelism, ZeRO-1/2/3 Optimizer, and Onman CUDA FlashAttention.

---

## 🌐 3D Parallelism Architecture

To train modern multi-billion parameter language models, memory and computation are partitioned across a 3-dimensional GPU mesh:

$$\text{World Size} = \text{TP} \times \text{PP} \times \text{DP}$$

```
                           3D Parallelism Grid
                 ┌──────────────────────────────────────┐
                 │       Pipeline Parallel (PP)         │
                 │  Stage 0  ───────────────► Stage 1   │
                 └──────┬───────────────────────┬───────┘
                        │                       │
      ┌─────────────────┴────────┐   ┌──────────┴──────────────┐
      │   Tensor Parallel (TP)   │   │   Tensor Parallel (TP)  │
      │  GPU 0  <-- AllReduce -- GPU 1  │   │  GPU 2  <-- AllReduce -- GPU 3  │
      └─────────┬────────────────┘   └──────────┬──────────────┘
                │                               │
                └─────── Data Parallel (DP) ────┘
                       ZeRO Gradient / Optimizer Sync
```

### 1. Tensor Parallelism (TP)
- **Attention Layer**: Multi-head attention projections are split column-wise across GPUs ($H_{\text{local}} = H / \text{TP}$). Each GPU runs the **Onman CUDA FlashAttention kernel** locally on its partition of heads with zero inter-GPU communication! The output linear layer is row-partitioned and synchronized with a single `All-Reduce`.
- **MLP Layer**: The gate/up projection is column-parallel ($2 \times \text{Intermediate} / \text{TP}$), and the down projection is row-parallel, followed by an `All-Reduce`.

### 2. Pipeline Parallelism (PP)
- Splits sequential transformer layers across $P$ pipeline stages.
- Employs the **1F1B (One Forward, One Backward)** schedule: during steady state, each GPU alternates between computing one forward micro-batch and one backward micro-batch, capping in-flight activation memory to $P \times \text{microbatch}$ instead of the entire batch.

### 3. Data Parallelism (DP) with ZeRO
- Eliminates memory redundancies across data-parallel ranks:
  - **ZeRO Stage 1**: Partitions FP32 Adam optimizer states (momentum and variance) across DP ranks (reduces memory from $16\Psi$ to $4\Psi + \frac{12\Psi}{N_{DP}}$ bytes).
  - **ZeRO Stage 2**: Partitions optimizer states and gradients via reduce-scatter ($8\Psi$ reduction).
  - **ZeRO Stage 3**: Partitions optimizer states, gradients, and model parameters layer-by-layer.

---

## 💾 Memory Breakdown: Standard DP vs ZeRO

For a model with $\Psi$ parameters trained in mixed precision (16-bit params + 16-bit grads + 32-bit master weights + 32-bit momentum + 32-bit variance):

| Strategy | Parameters | Gradients | Optimizer States | Total Memory (Model States) |
|---|---|---|---|---|
| **Standard DDP** | $2\Psi$ bytes | $2\Psi$ bytes | $12\Psi$ bytes | **$16\Psi$ bytes per GPU** |
| **ZeRO Stage 1** | $2\Psi$ bytes | $2\Psi$ bytes | $\frac{12\Psi}{N_{DP}}$ bytes | **$4\Psi + \frac{12\Psi}{N_{DP}}$ bytes** |
| **ZeRO Stage 2** | $2\Psi$ bytes | $\frac{2\Psi}{N_{DP}}$ bytes | $\frac{12\Psi}{N_{DP}}$ bytes | **$2\Psi + \frac{14\Psi}{N_{DP}}$ bytes** |
| **ZeRO Stage 3** | $\frac{2\Psi}{N_{DP}}$ bytes | $\frac{2\Psi}{N_{DP}}$ bytes | $\frac{12\Psi}{N_{DP}}$ bytes | **$\frac{16\Psi}{N_{DP}}$ bytes (near linear scaling)** |

---

## 🚀 Quick Start

### 1. Single GPU / Local Test Run

```bash
python engine/distributed/train.py \
  --vocab_size 16000 \
  --hidden_size 512 \
  --num_layers 8 \
  --num_heads 8 \
  --seq_len 512 \
  --batch_size 4 \
  --steps 50
```

### 2. Multi-GPU Distributed Run (2x GPUs with Tensor Parallelism)

```bash
torchrun --nproc_per_node=2 engine/distributed/train.py \
  --tp_size 2 \
  --zero_stage 1 \
  --hidden_size 1024 \
  --num_layers 16 \
  --num_heads 16 \
  --seq_len 1024
```

### 3. Multi-Node Training (e.g. 4 Nodes x 8 GPUs = 32 GPUs)

```bash
torchrun \
  --nnodes=4 \
  --nproc_per_node=8 \
  --rdzv_id=onman_job_1 \
  --rdzv_backend=c10d \
  --rdzv_endpoint=10.0.0.1:29500 \
  engine/distributed/train.py \
  --tp_size 4 \
  --pp_size 2 \
  --dp_size 4 \
  --zero_stage 2 \
  --batch_size 32 \
  --micro_batch_size 2
```

---

## 🧩 Programmatic API

```python
from engine.distributed.config import DistributedModelConfig, ParallelTopologyConfig, TrainingConfig
from engine.distributed.trainer import DistributedTrainer

# 1. Configure Model & Topology
model_config = DistributedModelConfig(hidden_size=1024, num_layers=16, num_heads=16)
topo_config = ParallelTopologyConfig(tp_size=2, zero_stage=2)
train_config = TrainingConfig(batch_size=8, micro_batch_size=2, learning_rate=3e-4)

# 2. Instantiate Trainer
trainer = DistributedTrainer(model_config, topo_config, train_config)

# 3. Train Step
metrics = trainer.train_step(input_ids, labels)
print(f"Step {metrics['global_step']}: Loss={metrics['loss']:.4f}, Speed={metrics['tokens_per_sec']:.1f} tok/s")
```
