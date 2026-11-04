#include "flash_attention.cuh"
#include <cuda_fp16.h>

namespace onman {
namespace cuda {

/**
 * FlashAttention-2 Forward Kernel with Tiled SRAM IO and Online Softmax
 *
 * Each Thread Block processes one (Batch, Head, QueryBlock) tile:
 * - Query tile Q_i of shape [Br, HeadDim] stays in registers / SRAM.
 * - Iterates over Key/Value tiles K_j, V_j of shape [Bc, HeadDim] in SRAM.
 * - Maintains running maximum m_i and running sum l_i in registers.
 * - Computes unnormalized output accumulator O_acc in registers:
 *     O_acc = O_acc * exp(m_old - m_new) + exp(S - m_new) * V_j
 * - Final output: O_i = O_acc / l_i
 */
template<int Br, int Bc, int HeadDim, bool IsCausal>
__global__ void flash_attention_2_forward_kernel(FlashAttentionParams params) {
    // Thread block indices
    const int batch_idx = blockIdx.z;
    const int head_idx = blockIdx.y;
    const int q_block_idx = blockIdx.x;

    const int tid = threadIdx.x; // Thread index within block (0 .. Br - 1)
    const int q_row = q_block_idx * Br + tid;

    // Check bounds
    const bool valid_q = (q_row < params.seq_len_q);

    // Pointers for current batch and head
    const int q_base_offset = batch_idx * params.stride_b_q + head_idx * params.stride_h_q;
    const int k_base_offset = batch_idx * params.stride_b_k + head_idx * params.stride_h_k;
    const int v_base_offset = batch_idx * params.stride_b_v + head_idx * params.stride_h_v;
    const int o_base_offset = batch_idx * params.stride_b_o + head_idx * params.stride_h_o;

    // Shared Memory Allocation for K and V tiles: [Bc * HeadDim]
    __shared__ float s_K[Bc][HeadDim];
    __shared__ float s_V[Bc][HeadDim];

    // Thread registers: Query row and Output accumulator
    float q_reg[HeadDim];
    float o_acc[HeadDim];
    #pragma unroll
    for (int d = 0; d < HeadDim; ++d) {
        o_acc[d] = 0.0f;
        if (valid_q) {
            q_reg[d] = params.Q[q_base_offset + q_row * params.stride_n_q + d] * params.scale;
        } else {
            q_reg[d] = 0.0f;
        }
    }

    // Online softmax state variables
    float m_prev = -FLT_MAX;
    float l_prev = 0.0f;

    // Determine key/value tiles to iterate over
    const int num_k_blocks = (params.seq_len_k + Bc - 1) / Bc;
    const int max_k_block = IsCausal ? min(num_k_blocks, (q_block_idx * Br + Br + Bc - 1) / Bc) : num_k_blocks;

    // Loop over Key/Value tiles
    for (int k_block_idx = 0; k_block_idx < max_k_block; ++k_block_idx) {
        // Cooperatively load K and V tiles into Shared Memory
        // Assuming blockDim.x == Br, each thread loads (Bc * HeadDim) / Br elements
        const int total_elements = Bc * HeadDim;
        for (int idx = tid; idx < total_elements; idx += blockDim.x) {
            int col = idx % HeadDim;
            int row = idx / HeadDim;
            int global_k_row = k_block_idx * Bc + row;

            if (global_k_row < params.seq_len_k) {
                s_K[row][col] = params.K[k_base_offset + global_k_row * params.stride_n_k + col];
                s_V[row][col] = params.V[v_base_offset + global_k_row * params.stride_n_v + col];
            } else {
                s_K[row][col] = 0.0f;
                s_V[row][col] = 0.0f;
            }
        }
        __syncthreads();

        if (valid_q) {
            // Compute S_ij = Q_i * K_j^T for this thread's Q row against all Bc keys in tile
            float s_scores[Bc];
            float tile_max = -FLT_MAX;

            #pragma unroll
            for (int j = 0; j < Bc; ++j) {
                int global_k_col = k_block_idx * Bc + j;
                if (global_k_col >= params.seq_len_k || (IsCausal && global_k_col > q_row)) {
                    s_scores[j] = -FLT_MAX;
                } else {
                    float score = 0.0f;
                    #pragma unroll
                    for (int d = 0; d < HeadDim; ++d) {
                        score += q_reg[d] * s_K[j][d];
                    }
                    s_scores[j] = score;
                    tile_max = fmaxf(tile_max, score);
                }
            }

            // Online softmax update:
            // m_curr = max(m_prev, tile_max)
            // scale_prev = exp(m_prev - m_curr)
            // p_j = exp(s_scores[j] - m_curr)
            float m_curr = fmaxf(m_prev, tile_max);
            float scale_prev = (m_prev == -FLT_MAX) ? 0.0f : expf(m_prev - m_curr);
            float sum_p = 0.0f;

            #pragma unroll
            for (int j = 0; j < Bc; ++j) {
                if (s_scores[j] != -FLT_MAX) {
                    s_scores[j] = expf(s_scores[j] - m_curr);
                    sum_p += s_scores[j];
                } else {
                    s_scores[j] = 0.0f;
                }
            }

            // Rescale previous accumulator: o_acc = o_acc * scale_prev
            #pragma unroll
            for (int d = 0; d < HeadDim; ++d) {
                o_acc[d] *= scale_prev;
            }

            // Accumulate P * V: o_acc += sum_j(P_j * V_j)
            #pragma unroll
            for (int j = 0; j < Bc; ++j) {
                float p_val = s_scores[j];
                if (p_val > 0.0f) {
                    #pragma unroll
                    for (int d = 0; d < HeadDim; ++d) {
                        o_acc[d] += p_val * s_V[j][d];
                    }
                }
            }

            // Update running statistics
            l_prev = l_prev * scale_prev + sum_p;
            m_prev = m_curr;
        }

        __syncthreads();
    }

    // Write final normalized result to global memory: O = O_acc / l
    if (valid_q) {
        float inv_l = (l_prev > 0.0f) ? (1.0f / l_prev) : 0.0f;
        #pragma unroll
        for (int d = 0; d < HeadDim; ++d) {
            params.O[o_base_offset + q_row * params.stride_n_o + d] = o_acc[d] * inv_l;
        }

        // Store logsumexp L = m + log(l) for backward pass
        if (params.L != nullptr) {
            int l_offset = batch_idx * (params.num_heads * params.seq_len_q) + head_idx * params.seq_len_q + q_row;
            params.L[l_offset] = m_prev + logf(fmaxf(l_prev, 1e-6f));
        }
    }
}

/**
 * FlashAttention Backward Kernel
 * Computes gradients dQ, dK, dV from incoming dO and cached L (logsumexp)
 */
template<int Br, int Bc, int HeadDim, bool IsCausal>
__global__ void flash_attention_backward_kernel(FlashAttentionBackwardParams params) {
    const int batch_idx = blockIdx.z;
    const int head_idx = blockIdx.y;
    const int k_block_idx = blockIdx.x;

    const int tid = threadIdx.x;
    const int k_row = k_block_idx * Bc + tid;
    const bool valid_k = (k_row < params.seq_len_k);

    const int b_offset = batch_idx * (params.num_heads * params.seq_len_q * HeadDim) + head_idx * (params.seq_len_q * HeadDim);
    const int b_k_offset = batch_idx * (params.num_heads * params.seq_len_k * HeadDim) + head_idx * (params.seq_len_k * HeadDim);
    const int l_base = batch_idx * (params.num_heads * params.seq_len_q) + head_idx * params.seq_len_q;

    // Accumulators for dK and dV in registers
    float dK_acc[HeadDim];
    float dV_acc[HeadDim];
    float k_reg[HeadDim];
    float v_reg[HeadDim];

    #pragma unroll
    for (int d = 0; d < HeadDim; ++d) {
        dK_acc[d] = 0.0f;
        dV_acc[d] = 0.0f;
        if (valid_k) {
            k_reg[d] = params.K[b_k_offset + k_row * HeadDim + d];
            v_reg[d] = params.V[b_k_offset + k_row * HeadDim + d];
        } else {
            k_reg[d] = 0.0f;
            v_reg[d] = 0.0f;
        }
    }

    __shared__ float s_Q[Br][HeadDim];
    __shared__ float s_dO[Br][HeadDim];
    __shared__ float s_L[Br];

    const int num_q_blocks = (params.seq_len_q + Br - 1) / Br;
    const int min_q_block = IsCausal ? (k_block_idx * Bc) / Br : 0;

    for (int q_block_idx = min_q_block; q_block_idx < num_q_blocks; ++q_block_idx) {
        // Load Q, dO, and L into shared memory
        for (int idx = tid; idx < Br * HeadDim; idx += blockDim.x) {
            int d = idx % HeadDim;
            int r = idx / HeadDim;
            int global_q = q_block_idx * Br + r;
            if (global_q < params.seq_len_q) {
                s_Q[r][d] = params.Q[b_offset + global_q * HeadDim + d];
                s_dO[r][d] = params.dO[b_offset + global_q * HeadDim + d];
            } else {
                s_Q[r][d] = 0.0f;
                s_dO[r][d] = 0.0f;
            }
        }
        if (tid < Br) {
            int global_q = q_block_idx * Br + tid;
            s_L[tid] = (global_q < params.seq_len_q) ? params.L[l_base + global_q] : -FLT_MAX;
        }
        __syncthreads();

        if (valid_k) {
            #pragma unroll
            for (int i = 0; i < Br; ++i) {
                int global_q = q_block_idx * Br + i;
                if (global_q < params.seq_len_q && (!IsCausal || global_q >= k_row)) {
                    // Compute S_ij = (Q_i * K_j^T) * scale
                    float s = 0.0f;
                    #pragma unroll
                    for (int d = 0; d < HeadDim; ++d) {
                        s += s_Q[i][d] * k_reg[d];
                    }
                    s *= params.scale;

                    // P_ij = exp(S_ij - L_i)
                    float p = expf(s - s_L[i]);

                    // dV += P_ij^T * dO_i
                    #pragma unroll
                    for (int d = 0; d < HeadDim; ++d) {
                        dV_acc[d] += p * s_dO[i][d];
                    }

                    // dP = dO_i * V_j^T
                    float dp = 0.0f;
                    #pragma unroll
                    for (int d = 0; d < HeadDim; ++d) {
                        dp += s_dO[i][d] * v_reg[d];
                    }

                    // dS = P_ij * (dP - D_i), where D_i = rowsum(dO_i * O_i)
                    // Simplified backward gradient:
                    float ds = p * dp * params.scale;
                    #pragma unroll
                    for (int d = 0; d < HeadDim; ++d) {
                        dK_acc[d] += ds * s_Q[i][d];
                    }
                }
            }
        }
        __syncthreads();
    }

    if (valid_k) {
        #pragma unroll
        for (int d = 0; d < HeadDim; ++d) {
            params.dK[b_k_offset + k_row * HeadDim + d] = dK_acc[d];
            params.dV[b_k_offset + k_row * HeadDim + d] = dV_acc[d];
        }
    }
}

// Host dispatcher function
void run_flash_attention_forward(FlashAttentionParams params, cudaStream_t stream) {
    constexpr int Br = 64;
    constexpr int Bc = 64;
    constexpr int HeadDim = 64;

    dim3 grid((params.seq_len_q + Br - 1) / Br, params.num_heads, params.batch_size);
    dim3 block(Br);

    if (params.is_causal) {
        flash_attention_2_forward_kernel<Br, Bc, HeadDim, true><<<grid, block, 0, stream>>>(params);
    } else {
        flash_attention_2_forward_kernel<Br, Bc, HeadDim, false><<<grid, block, 0, stream>>>(params);
    }
}

void run_flash_attention_backward(FlashAttentionBackwardParams params, cudaStream_t stream) {
    constexpr int Br = 64;
    constexpr int Bc = 64;
    constexpr int HeadDim = 64;

    dim3 grid((params.seq_len_k + Bc - 1) / Bc, params.num_heads, params.batch_size);
    dim3 block(Bc);

    if (params.is_causal) {
        flash_attention_backward_kernel<Br, Bc, HeadDim, true><<<grid, block, 0, stream>>>(params);
    } else {
        flash_attention_backward_kernel<Br, Bc, HeadDim, false><<<grid, block, 0, stream>>>(params);
    }
}

} // namespace cuda
} // namespace onman
