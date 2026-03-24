from __future__ import annotations

import importlib
import shlex
import sys

from .config import ModelConfig
from .hf_auth import resolve_hf_token


def _ensure_huggingface_hub_snapshot_download_compatibility() -> None:
    try:
        from huggingface_hub import constants
    except ModuleNotFoundError:
        return

    if hasattr(constants, "HF_HUB_ENABLE_HF_TRANSFER"):
        return

    # Notebook package upgrades can leave an older constants module in memory.
    loaded_constants = sys.modules.get("huggingface_hub.constants")
    if loaded_constants is not None:
        try:
            constants = importlib.reload(loaded_constants)
        except Exception:  # noqa: BLE001
            constants = loaded_constants

    if not hasattr(constants, "HF_HUB_ENABLE_HF_TRANSFER"):
        constants.HF_HUB_ENABLE_HF_TRANSFER = False


def download_model(model_config: ModelConfig, hf_token: str | None = None) -> str:
    token = hf_token or resolve_hf_token(prompt_if_missing=False)
    _ensure_huggingface_hub_snapshot_download_compatibility()
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
    parts.extend(model_config.extra_vllm_args)
    return " ".join(shlex.quote(part) for part in parts)
