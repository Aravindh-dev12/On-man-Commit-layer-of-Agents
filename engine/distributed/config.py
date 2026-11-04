from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DistributedModelConfig:
    """Configuration for Distributed Transformer Language Model."""
    vocab_size: int = 32000
    hidden_size: int = 1024
    num_layers: int = 16
    num_heads: int = 16
    intermediate_size: int = 4096
    max_seq_len: int = 2048
    norm_eps: float = 1e-6
    rope_theta: float = 10000.0
    use_flash_attention: bool = True
    dropout: float = 0.0
    tie_word_embeddings: bool = False


@dataclass
class ParallelTopologyConfig:
    """3D Parallelism Mesh Configuration (TP x PP x DP)."""
    tp_size: int = 1  # Tensor Parallel size
    pp_size: int = 1  # Pipeline Parallel size
    dp_size: int = 1  # Data Parallel size
    zero_stage: int = 1  # ZeRO stage (0=none, 1=opt states, 2=gradients, 3=params)


@dataclass
class TrainingConfig:
    """Distributed Training Hyperparameters."""
    batch_size: int = 4
    micro_batch_size: int = 1
    gradient_accumulation_steps: int = 4
    learning_rate: float = 3e-4
    min_learning_rate: float = 3e-5
    warmup_steps: int = 100
    max_steps: int = 1000
    weight_decay: float = 0.1
    max_grad_norm: float = 1.0
    fp16: bool = True
    bf16: bool = False
    checkpoint_interval: int = 500
    checkpoint_dir: str = "./checkpoints"
    seed: int = 42
