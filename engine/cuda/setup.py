from setuptools import setup
from torch.utils.cpp_extension import BuildExtension, CUDAExtension
import os

extra_compile_args = {
    'cxx': ['-O3'],
    'nvcc': [
        '-O3',
        '--use_fast_math',
        '-gencode=arch=compute_70,code=sm_70',
        '-gencode=arch=compute_75,code=sm_75',
        '-gencode=arch=compute_80,code=sm_80',
        '-gencode=arch=compute_86,code=sm_86',
        '-gencode=arch=compute_89,code=sm_89',
        '-gencode=arch=compute_90,code=sm_90',
    ]
}

setup(
    name='onman_cuda_attention',
    ext_modules=[
        CUDAExtension(
            name='onman_cuda_attention',
            sources=[
                'attention_binding.cpp',
                'flash_attention.cu',
            ],
            extra_compile_args=extra_compile_args,
        )
    ],
    cmdclass={
        'build_ext': BuildExtension
    }
)
