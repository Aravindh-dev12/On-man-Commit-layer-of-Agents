#pragma once

#include <cuda.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <float.h>
#include <math.h>

namespace onman {
namespace cuda {

// Block tiling hyperparameters for FlashAttention
// Br: Query block size along sequence length (number of queries per thread block)
// Bc: Key/Value block size along sequence length (number of keys/values per block)
// d: Head dimension (e.g., 64, 128)
constexpr int DEFAULT_BR = 64;
constexpr int DEFAULT_BC = 64;
constexpr int DEFAULT_HEAD_DIM = 64;
constexpr int WARP_SIZE = 32;

// Warp-level reduction primitives
__device__ __forceinline__ float warp_reduce_max(float val) {
    #pragma unroll
    for (int mask = WARP_SIZE / 2; mask > 0; mask >>= 1) {
        val = fmaxf(val, __shfl_xor_sync(0xffffffff, val, mask));
    }
    return val;
}

__device__ __forceinline__ float warp_reduce_sum(float val) {
    #pragma unroll
    for (int mask = WARP_SIZE / 2; mask > 0; mask >>= 1) {
        val += __shfl_xor_sync(0xffffffff, val, mask));
    }
    return val;
}

// Block-level reduction primitives using shared memory
template<int NUM_WARPS>
__device__ __forceinline__ float block_reduce_max(float val, float* shared_mem) {
    int lane = threadIdx.x % WARP_SIZE;
    int wid = threadIdx.x / WARP_SIZE;

    val = warp_reduce_max(val);
    if (lane == 0) {
        shared_mem[wid] = val;
    }
    __syncthreads();

    float block_max = -FLT_MAX;
    if (wid == 0) {
        block_max = (lane < NUM_WARPS) ? shared_mem[lane] : -FLT_MAX;
        block_max = warp_reduce_max(block_max);
    }
    __syncthreads();
    return block_max;
}

template<int NUM_WARPS>
__device__ __forceinline__ float block_reduce_sum(float val, float* shared_mem) {
    int lane = threadIdx.x % WARP_SIZE;
    int wid = threadIdx.x / WARP_SIZE;

    val = warp_reduce_sum(val);
    if (lane == 0) {
        shared_mem[wid] = val;
    }
    __syncthreads();

    float block_sum = 0.0f;
    if (wid == 0) {
        block_sum = (lane < NUM_WARPS) ? shared_mem[lane] : 0.0f;
        block_sum = warp_reduce_sum(block_sum);
    }
    __syncthreads();
    return block_sum;
}

// Metadata parameters passed to the FlashAttention CUDA kernel
struct FlashAttentionParams {
    const float* __restrict__ Q;      // [Batch, NumHeads, SeqLenQ, HeadDim]
    const float* __restrict__ K;      // [Batch, NumHeads, SeqLenK, HeadDim]
    const float* __restrict__ V;      // [Batch, NumHeads, SeqLenK, HeadDim]
    float* __restrict__ O;            // [Batch, NumHeads, SeqLenQ, HeadDim]
    float* __restrict__ L;            // [Batch, NumHeads, SeqLenQ] logsumexp for backward pass
    
    int batch_size;
    int num_heads;
    int seq_len_q;
    int seq_len_k;
    int head_dim;
    float scale;                      // 1.0f / sqrt(head_dim)
    bool is_causal;

    // Strides for [B, H, N, D] layout
    int stride_b_q;
    int stride_h_q;
    int stride_n_q;
    int stride_b_k;
    int stride_h_k;
    int stride_n_k;
    int stride_b_v;
    int stride_h_v;
    int stride_n_v;
    int stride_b_o;
    int stride_h_o;
    int stride_n_o;
};

// Backward pass parameters
struct FlashAttentionBackwardParams {
    const float* __restrict__ Q;
    const float* __restrict__ K;
    const float* __restrict__ V;
    const float* __restrict__ O;
    const float* __restrict__ dO;
    const float* __restrict__ L;      // Logsumexp from forward
    float* __restrict__ dQ;
    float* __restrict__ dK;
    float* __restrict__ dV;

    int batch_size;
    int num_heads;
    int seq_len_q;
    int seq_len_k;
    int head_dim;
    float scale;
    bool is_causal;

    int stride_b;
    int stride_h;
    int stride_n;
};

} // namespace cuda
} // namespace onman
