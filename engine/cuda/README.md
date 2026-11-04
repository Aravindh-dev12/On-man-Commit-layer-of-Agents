# Onman High-Performance CUDA Attention Kernel

Fast, IO-aware exact Attention kernel implemented in low-level CUDA C++ with shared memory tiling and online softmax. Designed for transformer training and inference.

---

## ⚡ Background: The Memory Wall in Standard Attention

Standard transformer self-attention calculates:
$$\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{Q K^T}{\sqrt{d}}\right) V$$

For batch size $B$, number of heads $H$, sequence length $N$, and head dimension $d$:
1. $S = Q K^T \in \mathbb{R}^{B \times H \times N \times N}$ is written to GPU High-Bandwidth Memory (HBM): **$O(N^2)$ memory footprint**.
2. $P = \text{softmax}(S)$ is read from HBM, scaled, exponentiated, and written back to HBM: **$O(N^2)$ memory roundtrips**.
3. $O = P V$ is read from HBM and written back: **$O(N^2)$ memory bandwidth**.

Modern GPUs (NVIDIA A100/H100/RTX) have massive compute capabilities (>300 TFLOPS), but GPU HBM bandwidth is a bottleneck (1.5–3 TB/s). Standard attention is **memory-bandwidth bound**.

```
Standard Attention (Quadratic HBM IO):
  GPU HBM (Slow, 1.5 TB/s)  <===========> SRAM (Fast, 19 TB/s)
  Loads Q, K                ---------->   Computes Q K^T
  Writes S [N x N] (HBM)    <----------   
  Reads S [N x N]           ---------->   Computes Softmax(S)
  Writes P [N x N] (HBM)    <----------
  Reads P & V               ---------->   Computes P @ V
  Writes O [N x d] (HBM)    <----------
```

---

## 🚀 FlashAttention: IO-Aware Tiling & Online Softmax

Onman's CUDA kernel uses **Shared Memory (SRAM) tiling** and **online softmax** to compute exact attention in a single fused GPU kernel call with **$O(N)$ HBM memory access**. The $N \times N$ attention matrix is never materialized in global GPU memory.

```
Onman FlashAttention (Linear HBM IO):
  GPU HBM                   <===========> On-Chip Shared Memory (SRAM)
  Loads Q tile [Br x d]     ---------->   Kept in registers / SRAM
  Loads K, V tile [Bc x d]  ---------->   Tiled in SRAM
                                          Computes S_tile = Q_tile @ K_tile^T
                                          Computes online softmax running max & sum
                                          Accumulates O_acc in registers
  Writes final O [N x d]    <----------   Normalized only once at end of loop!
```

---

## 🧮 Online Softmax Algorithm

To compute softmax row-wise across blocks $j=1 \dots T_c$ without storing the whole row:

Given a vector $x \in \mathbb{R}^N$ split into two blocks $x = [x^{(1)}, x^{(2)}]$:
$$m(x) = \max(x) = \max(m(x^{(1)}), m(x^{(2)}))$$
$$l(x) = \sum_{i} e^{x_i - m(x)} = e^{m(x^{(1)}) - m(x)} l(x^{(1)}) + e^{m(x^{(2)}) - m(x)} l(x^{(2)})$$

### In the Kernel:
For each block $K_j, V_j$:
1. Compute tile scores $S_{ij} = \frac{Q_i K_j^T}{\sqrt{d}} \in \mathbb{R}^{B_r \times B_c}$.
2. Find tile row-max $\tilde{m} = \max_c(S_{ij})$.
3. Update global running max:
   $$m^{new} = \max(m^{old}, \tilde{m})$$
4. Compute unnormalized probabilities:
   $$P_{ij} = \exp(S_{ij} - m^{new})$$
5. Rescale previous sum and accumulator:
   $$\alpha = \exp(m^{old} - m^{new})$$
   $$l^{new} = l^{old} \cdot \alpha + \sum_{c} P_{ij}$$
   $$O_{acc}^{new} = O_{acc}^{old} \cdot \alpha + P_{ij} V_j$$
6. At loop exit, normalize:
   $$O_i = \frac{O_{acc}}{l_i}, \quad L_i = m_i + \log(l_i)$$

$L_i$ (the logsumexp) is stored for the backward pass to recompute attention probabilities without storing $P$.

---

## 📁 Source Code Structure

- [`flash_attention.cuh`](./flash_attention.cuh): CUDA device headers, warp shuffle reduction primitives (`warp_reduce_max`, `warp_reduce_sum`), parameter structs.
- [`flash_attention.cu`](./flash_attention.cu): Core CUDA `flash_attention_2_forward_kernel` and `flash_attention_backward_kernel` implementations.
- [`attention_binding.cpp`](./attention_binding.cpp): PyTorch C++ extension binding using Pybind11.
- [`ops.py`](./ops.py): High-level Python API with differentiable `torch.autograd.Function` and `FlashAttentionLayer`.
- [`setup.py`](./setup.py): Setuptools build script compiling with NVCC.
- [`benchmark.py`](./benchmark.py): Latency, memory, and TFLOPS profiler.

---

## 💻 Usage

```python
import torch
from engine.cuda.ops import onman_flash_attention, FlashAttentionLayer

# 1. Direct function call
B, H, SeqLen, HeadDim = 2, 8, 2048, 64
q = torch.randn(B, H, SeqLen, HeadDim, device="cuda")
k = torch.randn(B, H, SeqLen, HeadDim, device="cuda")
v = torch.randn(B, H, SeqLen, HeadDim, device="cuda")

# Returns exact causal attention output in O(N) memory
out = onman_flash_attention(q, k, v, is_causal=True)

# 2. Module in Transformer
attn_layer = FlashAttentionLayer(hidden_size=512, num_heads=8, is_causal=True).cuda()
x = torch.randn(B, SeqLen, 512, device="cuda")
y = attn_layer(x)
```

---

## 🛠️ Compilation

To compile the CUDA extension directly into your Python environment:

```bash
cd engine/cuda
python setup.py install
```
