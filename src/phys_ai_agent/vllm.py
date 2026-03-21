from __future__ import annotations

import shlex

from huggingface_hub import snapshot_download

from .config import ModelConfig


def download_model(model_config: ModelConfig, hf_token: str) -> str:
    return snapshot_download(
        repo_id=model_config.repo_id,
        token=hf_token,
        local_dir=model_config.local_dir,
        local_dir_use_symlinks=False,
    )


def build_vllm_server_command(
    model_config: ModelConfig,
    host: str = "0.0.0.0",
    port: int = 8000,
    gpu_memory_utilization: float = 0.80,
) -> str:
    parts = [
        "python",
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        model_config.local_dir,
        "--tokenizer",
        model_config.local_dir,
        "--served-model-name",
        model_config.served_model_name,
        "--host",
        host,
        "--port",
        str(port),
        "--gpu-memory-utilization",
        f"{gpu_memory_utilization:.2f}",
    ]
    return " ".join(shlex.quote(part) for part in parts)
