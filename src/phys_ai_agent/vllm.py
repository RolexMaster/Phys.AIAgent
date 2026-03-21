from __future__ import annotations

import shlex

from .config import ModelConfig
from .hf_auth import resolve_hf_token


def download_model(model_config: ModelConfig, hf_token: str | None = None) -> str:
    token = hf_token or resolve_hf_token(prompt_if_missing=False)
    try:
        from huggingface_hub import snapshot_download
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "huggingface_hub is not installed. Install it before calling download_model()."
        ) from exc
    return snapshot_download(
        repo_id=model_config.repo_id,
        token=token,
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
