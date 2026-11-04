#include <torch/extension.h>
#include "flash_attention.cuh"

namespace onman {
namespace cuda {

void run_flash_attention_forward(FlashAttentionParams params, cudaStream_t stream);
void run_flash_attention_backward(FlashAttentionBackwardParams params, cudaStream_t stream);

std::vector<torch::Tensor> flash_attention_forward(
    torch::Tensor Q,
    torch::Tensor K,
    torch::Tensor V,
    bool is_causal,
    float scale
) {
    TORCH_CHECK(Q.is_cuda(), "Q must be a CUDA tensor");
    TORCH_CHECK(K.is_cuda(), "K must be a CUDA tensor");
    TORCH_CHECK(V.is_cuda(), "V must be a CUDA tensor");
    TORCH_CHECK(Q.dtype() == torch::kFloat32, "Only float32 currently supported in reference binding");

    const int batch_size = Q.size(0);
    const int num_heads = Q.size(1);
    const int seq_len_q = Q.size(2);
    const int head_dim = Q.size(3);
    const int seq_len_k = K.size(2);

    TORCH_CHECK(head_dim == DEFAULT_HEAD_DIM, "Head dimension must match compiled kernel dimension (64)");

    if (scale <= 0.0f) {
        scale = 1.0f / std::sqrt(static_cast<float>(head_dim));
    }

    auto O = torch::empty_like(Q);
    auto L = torch::empty({batch_size, num_heads, seq_len_q}, Q.options());

    FlashAttentionParams params;
    params.Q = Q.data_ptr<float>();
    params.K = K.data_ptr<float>();
    params.V = V.data_ptr<float>();
    params.O = O.data_ptr<float>();
    params.L = L.data_ptr<float>();

    params.batch_size = batch_size;
    params.num_heads = num_heads;
    params.seq_len_q = seq_len_q;
    params.seq_len_k = seq_len_k;
    params.head_dim = head_dim;
    params.scale = scale;
    params.is_causal = is_causal;

    params.stride_b_q = Q.stride(0);
    params.stride_h_q = Q.stride(1);
    params.stride_n_q = Q.stride(2);

    params.stride_b_k = K.stride(0);
    params.stride_h_k = K.stride(1);
    params.stride_n_k = K.stride(2);

    params.stride_b_v = V.stride(0);
    params.stride_h_v = V.stride(1);
    params.stride_n_v = V.stride(2);

    params.stride_b_o = O.stride(0);
    params.stride_h_o = O.stride(1);
    params.stride_n_o = O.stride(2);

    cudaStream_t stream = c10::cuda::getCurrentCUDAStream();
    run_flash_attention_forward(params, stream);

    return {O, L};
}

std::vector<torch::Tensor> flash_attention_backward(
    torch::Tensor dO,
    torch::Tensor Q,
    torch::Tensor K,
    torch::Tensor V,
    torch::Tensor O,
    torch::Tensor L,
    bool is_causal,
    float scale
) {
    auto dQ = torch::zeros_like(Q);
    auto dK = torch::zeros_like(K);
    auto dV = torch::zeros_like(V);

    const int batch_size = Q.size(0);
    const int num_heads = Q.size(1);
    const int seq_len_q = Q.size(2);
    const int head_dim = Q.size(3);
    const int seq_len_k = K.size(2);

    if (scale <= 0.0f) {
        scale = 1.0f / std::sqrt(static_cast<float>(head_dim));
    }

    FlashAttentionBackwardParams params;
    params.Q = Q.data_ptr<float>();
    params.K = K.data_ptr<float>();
    params.V = V.data_ptr<float>();
    params.O = O.data_ptr<float>();
    params.dO = dO.data_ptr<float>();
    params.L = L.data_ptr<float>();
    params.dQ = dQ.data_ptr<float>();
    params.dK = dK.data_ptr<float>();
    params.dV = dV.data_ptr<float>();

    params.batch_size = batch_size;
    params.num_heads = num_heads;
    params.seq_len_q = seq_len_q;
    params.seq_len_k = seq_len_k;
    params.head_dim = head_dim;
    params.scale = scale;
    params.is_causal = is_causal;

    cudaStream_t stream = c10::cuda::getCurrentCUDAStream();
    run_flash_attention_backward(params, stream);

    return {dQ, dK, dV};
}

} // namespace cuda
} // namespace onman

PYBIND11_MODULE(TORCH_EXTENSION_NAME, m) {
    m.def("forward", &onman::cuda::flash_attention_forward, "Onman FlashAttention Forward (CUDA)");
    m.def("backward", &onman::cuda::flash_attention_backward, "Onman FlashAttention Backward (CUDA)");
}
