from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from openai import OpenAI

from .bridge_session import BridgeSession
from .config import RuntimeConfig


def configure_file_logger(log_file: str | Path, logger_name: str = "mcp_bridge") -> logging.Logger:
    log_path = Path(log_file)

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", datefmt="%H:%M:%S")
    )
    logger.addHandler(file_handler)
    logger.propagate = False

    root = logging.getLogger()
    for handler in root.handlers[:]:
        if isinstance(handler, logging.StreamHandler):
            root.removeHandler(handler)
    root.setLevel(logging.WARNING)

    for noisy in ("openai", "httpx", "fastmcp", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
        logging.getLogger(noisy).propagate = False

    return logger


async def run_preset_queries(
    runtime_config: RuntimeConfig,
    logger: logging.Logger | None = None,
    session_temp: float = 0.2,
    session_max_tokens: int = 512,
    session_max_turns: int | None = None,
    language: str = "en",
) -> list[dict[str, Any]]:
    logger = logger or configure_file_logger(runtime_config.log_file)

    logger.info("===== SETUP =====")
    logger.info(f"[ENV] MCP_URL={runtime_config.mcp_url}")
    logger.info(f"[ENV] LLM_BASE_URL={runtime_config.llm_base_url}")
    logger.info(f"[ENV] LLM_MODEL={runtime_config.llm_model}")
    logger.info(
        "[ENV] TEMP=%s, MAX_TOKENS=%s, MAX_TURNS=%s",
        runtime_config.temp,
        runtime_config.max_tokens,
        runtime_config.max_turns,
    )

    results: list[dict[str, Any]] = []
    transport = StreamableHttpTransport(url=runtime_config.mcp_url)
    mcp = Client(transport)

    async with mcp:
        started_at = time.perf_counter()
        await mcp.ping()
        logger.info(f"[MCP] ping OK ({(time.perf_counter() - started_at):.2f}s)")

        mcp_tools = await mcp.list_tools()
        logger.info(f"[MCP] tools count = {len(mcp_tools)}")
        for tool in mcp_tools[:30]:
            name = getattr(tool, "name", None) or tool.get("name")
            logger.info(f"  - {name}")
        if len(mcp_tools) > 30:
            logger.info(f"  ... (+{len(mcp_tools) - 30} more)")

        logger.info("[LLM] waiting for readiness check...")
        wait_for_llm_ready(
            base_url=runtime_config.llm_base_url,
            model=runtime_config.llm_model,
            api_key=runtime_config.llm_api_key,
            logger=logger,
        )
        logger.info("[LLM] readiness check passed")

        llm = OpenAI(base_url=runtime_config.llm_base_url, api_key=runtime_config.llm_api_key)
        session = BridgeSession(
            llm=llm,
            mcp=mcp,
            mcp_tools=mcp_tools,
            temp=session_temp,
            max_tokens=session_max_tokens,
            max_turns=session_max_turns or runtime_config.max_turns,
            language=language,
        )

        logger.info("MCP Bridge preset runner. (no interactive REPL)")
        logger.info(f"Preset query count = {len(runtime_config.preset_queries)}")

        for query in runtime_config.preset_queries:
            session.reset()
            print(f"you> {query}")

            try:
                result = await session.handle_one_turn(query, model=runtime_config.llm_model, debug=True)
                results.append(result)

                print("[AIAGENT DEBUG]")
                print(json.dumps(result, ensure_ascii=False, indent=2))

                turns = result.get("turns") or []
                used_any_tool = any(turn.get("tool_calls") for turn in turns)
                has_tool_error = _has_tool_error(turns)

                if (not used_any_tool) or has_tool_error:
                    final_msg = "MCP tool execution failed. Check the log for details."
                else:
                    final_msg = result.get("final_answer")

                print("[AIAGENT FINAL]", final_msg)
                print()
                print()
            except Exception as exc:  # noqa: BLE001
                logger.exception(f"[PRESET] handle_one_turn error for '{query}': {exc}")
                print(f"[AIAGENT ERROR] {type(exc).__name__}: {exc}")

    logger.info("All preset queries finished. Exiting.")
    return results


def smoke_test_chat_completion(
    base_url: str,
    model: str,
    api_key: str = "EMPTY",
    message: str = "Reply with OK.",
    max_tokens: int = 128,
) -> str:
    client = OpenAI(base_url=base_url, api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": message}],
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


def wait_for_llm_ready(
    base_url: str,
    model: str,
    api_key: str = "EMPTY",
    timeout_sec: int = 180,
    poll_interval_sec: float = 3.0,
    logger: logging.Logger | None = None,
) -> None:
    client = OpenAI(base_url=base_url, api_key=api_key)
    deadline = time.monotonic() + timeout_sec
    last_error: Exception | None = None
    attempt = 0

    while time.monotonic() < deadline:
        attempt += 1
        try:
            models = client.models.list()
            model_ids = [getattr(item, "id", "") for item in getattr(models, "data", [])]
            if logger:
                logger.info("[LLM] attempt %s: models=%s", attempt, model_ids or "[]")

            if model_ids and model not in model_ids:
                raise RuntimeError(
                    f"Configured model {model!r} is not served by {base_url}. Available: {model_ids}"
                )

            response_text = smoke_test_chat_completion(
                base_url=base_url,
                model=model,
                api_key=api_key,
                max_tokens=8,
            )
            if logger:
                logger.info("[LLM] attempt %s: chat smoke test OK (%r)", attempt, response_text)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if logger:
                logger.warning("[LLM] attempt %s failed: %s: %s", attempt, type(exc).__name__, exc)
            time.sleep(poll_interval_sec)

    error_message = (
        f"LLM endpoint was not ready within {timeout_sec}s. "
        f"base_url={base_url}, model={model}"
    )
    if last_error is not None:
        raise RuntimeError(error_message) from last_error
    raise RuntimeError(error_message)


def _has_tool_error(turns: list[dict[str, Any]]) -> bool:
    for turn in turns:
        for tool_result in turn.get("tool_results") or []:
            result = tool_result.get("result") or {}
            if not result.get("ok", False):
                return True
    return False
