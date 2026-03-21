from __future__ import annotations

from .config import MODEL_CONFIGS, ModelConfig, RuntimeConfig, resolve_model_config, resolve_runtime_config
from .hf_auth import login_to_huggingface, resolve_hf_token

__all__ = [
    "MODEL_CONFIGS",
    "ModelConfig",
    "RuntimeConfig",
    "resolve_model_config",
    "resolve_runtime_config",
    "resolve_hf_token",
    "login_to_huggingface",
    "configure_file_logger",
    "run_preset_queries",
    "smoke_test_chat_completion",
    "build_vllm_server_command",
    "download_model",
]


def __getattr__(name: str):
    if name in {"configure_file_logger", "run_preset_queries", "smoke_test_chat_completion"}:
        from .runner import configure_file_logger, run_preset_queries, smoke_test_chat_completion

        exports = {
            "configure_file_logger": configure_file_logger,
            "run_preset_queries": run_preset_queries,
            "smoke_test_chat_completion": smoke_test_chat_completion,
        }
        return exports[name]
    if name in {"build_vllm_server_command", "download_model"}:
        from .vllm import build_vllm_server_command, download_model

        exports = {
            "build_vllm_server_command": build_vllm_server_command,
            "download_model": download_model,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
