from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelConfig:
    family: str
    repo_id: str
    local_dir: str
    served_model_name: str
    base_url: str = "http://127.0.0.1:8000/v1"
    extra_vllm_args: tuple[str, ...] = ()


MODEL_CONFIGS: dict[str, ModelConfig] = {
    "llama": ModelConfig(
        family="llama",
        repo_id="meta-llama/Llama-3.1-8B-Instruct",
        local_dir="/content/models/llama-3.1-8b-instruct",
        served_model_name="meta-llama/Llama-3.1-8B-Instruct",
    ),
    "qwen": ModelConfig(
        family="qwen",
        repo_id="Qwen/Qwen2.5-7B-Instruct",
        local_dir="/content/models/qwen2.5-7b-instruct",
        served_model_name="Qwen/Qwen2.5-7B-Instruct",
    ),
    "qwen3_4": ModelConfig(
        family="qwen3_4",
        repo_id="Qwen/Qwen3-4B",
        local_dir="/content/models/qwen3-4b",
        served_model_name="Qwen/Qwen3-4B",
        extra_vllm_args=("--enable-reasoning", "--reasoning-parser", "deepseek_r1"),
    ),
    "qwen3_8": ModelConfig(
        family="qwen3_8",
        repo_id="Qwen/Qwen3-8B",
        local_dir="/content/models/qwen3-8b",
        served_model_name="Qwen/Qwen3-8B",
        extra_vllm_args=("--enable-reasoning", "--reasoning-parser", "deepseek_r1"),
    ),
    "qwen3_14": ModelConfig(
        family="qwen3_14",
        repo_id="Qwen/Qwen3-14B",
        local_dir="/content/models/qwen3-14b",
        served_model_name="Qwen/Qwen3-14B",
        extra_vllm_args=("--enable-reasoning", "--reasoning-parser", "deepseek_r1"),
    ),
    "qwen3_32": ModelConfig(
        family="qwen3_32",
        repo_id="Qwen/Qwen3-32B",
        local_dir="/content/models/qwen3-32b",
        served_model_name="Qwen/Qwen3-32B",
        extra_vllm_args=("--enable-reasoning", "--reasoning-parser", "deepseek_r1"),
    ),
}


@dataclass(frozen=True)
class RuntimeConfig:
    project_root: Path
    model_family: str
    model_repo_id: str
    model_local_dir: str
    served_model_name: str
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    mcp_url: str
    max_turns: int
    temp: float
    max_tokens: int
    log_file: Path
    scenario_dir: Path
    scenario_name: str
    scenario_file: Path
    preset_queries: list[str]
    scenario_data: dict[str, Any]


def resolve_model_config(model_family: str, model_configs: dict[str, ModelConfig] | None = None) -> ModelConfig:
    model_configs = model_configs or MODEL_CONFIGS
    normalized = _normalize_model_family(model_family)
    if normalized not in model_configs:
        supported = ", ".join(sorted(model_configs))
        raise ValueError(f"Unsupported MODEL_FAMILY: {model_family}. Supported: {supported}")
    return model_configs[normalized]


def load_scenario_file(scenario_file: str | Path) -> dict[str, Any]:
    scenario_path = Path(scenario_file)
    scenario_data = json.loads(scenario_path.read_text(encoding="utf-8"))
    queries = scenario_data.get("queries")
    if not isinstance(queries, list) or not all(isinstance(query, str) for query in queries):
        raise ValueError(f"Scenario file must contain a string list in 'queries': {scenario_path}")
    return scenario_data


def resolve_runtime_config(
    project_root: str | Path,
    default_model_family: str = "qwen3_14",
    model_configs: dict[str, ModelConfig] | None = None,
) -> RuntimeConfig:
    root = Path(project_root).resolve()
    model_family = os.getenv("MODEL_FAMILY", default_model_family).lower()
    model_cfg = resolve_model_config(model_family, model_configs=model_configs)

    scenario_dir_env = os.getenv("SCENARIO_DIR")
    scenario_dir = _resolve_path(root, scenario_dir_env) if scenario_dir_env else root / "scenarios"

    scenario_name = os.getenv("SCENARIO_NAME", "eots_advanced_commands_en")
    scenario_file_env = os.getenv("SCENARIO_FILE")
    if scenario_file_env:
        scenario_file = _resolve_path(root, scenario_file_env)
    else:
        scenario_file = scenario_dir / f"{scenario_name}.json"

    scenario_data = load_scenario_file(scenario_file)
    preset_queries = list(scenario_data["queries"])

    return RuntimeConfig(
        project_root=root,
        model_family=model_cfg.family,
        model_repo_id=model_cfg.repo_id,
        model_local_dir=model_cfg.local_dir,
        served_model_name=model_cfg.served_model_name,
        llm_base_url=os.getenv("LLM_BASE_URL", model_cfg.base_url),
        llm_model=os.getenv("LLM_MODEL", model_cfg.served_model_name),
        llm_api_key=os.getenv("LLM_API_KEY", "EMPTY"),
        mcp_url=os.getenv("MCP_URL", "https://page-romantic-webpage-terrace.trycloudflare.com/mcp"),
        max_turns=int(os.getenv("MAX_TURNS", "8")),
        temp=_resolve_temperature(),
        max_tokens=int(os.getenv("MAX_TOKENS", "512")),
        log_file=_resolve_path(root, os.getenv("LOG_FILE", "mcp_bridge.log")),
        scenario_dir=scenario_dir,
        scenario_name=scenario_name,
        scenario_file=scenario_file,
        preset_queries=preset_queries,
        scenario_data=scenario_data,
    )


def _resolve_path(project_root: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return project_root / path


def _normalize_model_family(model_family: str) -> str:
    normalized = model_family.lower().replace("-", "_")
    return re.sub(r"^(qwen3_\d+)b$", r"\1", normalized)


def _resolve_temperature(default: float = 0.2) -> float:
    for key in ("AIAGENT_TEMP", "LLM_TEMP", "MODEL_TEMP"):
        raw = os.getenv(key)
        if raw:
            return float(raw)

    raw_temp = os.getenv("TEMP")
    if raw_temp:
        try:
            return float(raw_temp)
        except ValueError:
            pass

    return default
