"""
Distributed Training Launcher Script
Launches training for Transformer LLMs across multiple GPUs with 3D Parallelism and ZeRO.

Usage:
  torchrun --nproc_per_node=2 engine/distributed/train.py --tp_size 2 --zero_stage 1
  python engine/distributed/train.py --steps 10
"""

import os
import sys
import argparse
import torch
import torch.distributed as dist

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from engine.distributed.config import DistributedModelConfig, ParallelTopologyConfig, TrainingConfig
from engine.distributed.trainer import DistributedTrainer


def parse_args():
    parser = argparse.ArgumentParser(description="Onman Distributed LLM Training")
    parser.add_argument("--vocab_size", type=int, default=16000, help="Vocabulary size")
    parser.add_argument("--hidden_size", type=int, default=512, help="Hidden dimension")
    parser.add_argument("--num_layers", type=int, default=8, help="Number of transformer layers")
    parser.add_argument("--num_heads", type=int, default=8, help="Number of attention heads")
    parser.add_argument("--seq_len", type=int, default=512, help="Sequence length")
    parser.add_argument("--batch_size", type=int, default=4, help="Global batch size")
    parser.add_argument("--micro_batch_size", type=int, default=2, help="Micro batch size")
    parser.add_argument("--tp_size", type=int, default=1, help="Tensor Parallel world size")
    parser.add_argument("--pp_size", type=int, default=1, help="Pipeline Parallel world size")
    parser.add_argument("--dp_size", type=int, default=1, help="Data Parallel world size")
    parser.add_argument("--zero_stage", type=int, default=1, choices=[0, 1, 2, 3], help="ZeRO Stage")
    parser.add_argument("--lr", type=float, default=3e-4, help="Learning rate")
    parser.add_argument("--steps", type=int, default=20, help="Number of training steps")
    parser.add_argument("--fp16", action="store_true", default=True, help="Enable FP16 mixed precision")
    return parser.parse_args()


def init_distributed():
    """Initializes standard PyTorch distributed process group if launched via torchrun."""
    if "RANK" in os.environ and "WORLD_SIZE" in os.environ:
        backend = "nccl" if torch.cuda.is_available() and sys.platform != "win32" else "gloo"
        dist.init_process_group(backend=backend)
        return dist.get_rank(), dist.get_world_size()
    return 0, 1


def main():
    args = parse_args()
    rank, world_size = init_distributed()

    if rank == 0:
        print("==================================================================")
        print("           Onman Distributed LLM Training Engine                  ")
        print(f" World Size: {world_size} | TP: {args.tp_size} | PP: {args.pp_size} | ZeRO Stage: {args.zero_stage}")
        print(f" Model: Hidden={args.hidden_size}, Layers={args.num_layers}, Heads={args.num_heads}, SeqLen={args.seq_len}")
        print("==================================================================")

    model_config = DistributedModelConfig(
        vocab_size=args.vocab_size,
        hidden_size=args.hidden_size,
        num_layers=args.num_layers,
        num_heads=args.num_heads,
        intermediate_size=args.hidden_size * 4,
        max_seq_len=args.seq_len,
    )

    topo_config = ParallelTopologyConfig(
        tp_size=args.tp_size,
        pp_size=args.pp_size,
        dp_size=args.dp_size,
        zero_stage=args.zero_stage,
    )

    train_config = TrainingConfig(
        batch_size=args.batch_size,
        micro_batch_size=args.micro_batch_size,
        learning_rate=args.lr,
        max_steps=args.steps,
        fp16=args.fp16,
    )

    trainer = DistributedTrainer(model_config, topo_config, train_config)

    # Synthetic training loop
    for step in range(args.steps):
        # Generate random batch of token IDs
        input_ids = torch.randint(
            0, args.vocab_size, (args.batch_size, args.seq_len), device=trainer.device
        )
        labels = input_ids.clone()

        metrics = trainer.train_step(input_ids, labels)

        if rank == 0 and (step % 5 == 0 or step == args.steps - 1):
            print(
                f"Step {metrics['global_step']:4d} | "
                f"Loss: {metrics['loss']:.4f} | "
                f"LR: {metrics['lr']:.2e} | "
                f"Speed: {metrics['tokens_per_sec']:8.1f} tok/s | "
                f"Step Time: {metrics['step_time_ms']:6.1f} ms"
            )

    if rank == 0:
        print("\n[Onman] Training completed successfully!")


if __name__ == "__main__":
    main()
