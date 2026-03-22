from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from fastmcp import Client
from openai import OpenAI

from .agent_prompts import AgentLanguage, build_system_prompt

__version__ = "0.1.0-local"
__commit__ = "local"

TOOLCALL_TEXT_BLOCK = re.compile(r"<tool_call>.*?</tool_call>", re.DOTALL)


def pretty_json(obj: Any, limit: int = 1000) -> str:
    try:
        text = json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        text = str(obj)
    return text if len(text) <= limit else text[:limit] + "\n... (truncated)"


def extract_toolcalls_from_text(text: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    if not text or "<tool_call>" not in text:
        return calls

    for part in text.split("<tool_call>")[1:]:
        brace_start = part.find("{")
        if brace_start < 0:
            continue

        depth = 0
        brace_end: int | None = None
        for idx in range(brace_start, len(part)):
            char = part[idx]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    brace_end = idx
                    break

        if brace_end is None:
            continue

        try:
            parsed = json.loads(part[brace_start : brace_end + 1])
        except Exception:
            continue

        name = parsed.get("name")
        arguments = parsed.get("arguments", {}) or {}
        if isinstance(name, str) and isinstance(arguments, dict):
            calls.append({"name": name, "arguments": arguments})

    return calls


def strip_toolcall_blocks(text: str) -> str:
    if not text:
        return ""
    return TOOLCALL_TEXT_BLOCK.sub("", text).strip()


def requires_params_wrapper(schema_json: dict[str, Any]) -> bool:
    if not isinstance(schema_json, dict):
        return False
    properties = schema_json.get("properties", {})
    required = set(schema_json.get("required", []))
    return "params" in properties and "params" in required


def _tool_name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        return tool.get("name")
    return getattr(tool, "name", None)


def build_name_maps(mcp_tools: list[Any]) -> tuple[dict[str, str], dict[str, str]]:
    llm_to_mcp: dict[str, str] = {}
    mcp_to_llm: dict[str, str] = {}
    for tool in mcp_tools:
        name = _tool_name(tool)
        if not name:
            continue
        llm_name = name.replace(".", "_")
        llm_to_mcp[llm_name] = name
        mcp_to_llm[name] = llm_name
    return llm_to_mcp, mcp_to_llm


def build_tools_block(mcp_tools: list[Any]) -> str:
    items: list[dict[str, Any]] = []
    for tool in mcp_tools:
        name = _tool_name(tool)
        if not name:
            continue

        if isinstance(tool, dict):
            schema = (
                tool.get("input_schema")
                or tool.get("inputSchema")
                or {"type": "object", "properties": {}}
            )
        else:
            schema = (
                getattr(tool, "input_schema", None)
                or getattr(tool, "inputSchema", None)
                or {"type": "object", "properties": {}}
            )

        if hasattr(schema, "model_dump"):
            schema = schema.model_dump()
        if not isinstance(schema, dict):
            schema = {"raw": str(schema)}

        items.append({"name": name.replace(".", "_"), "parameters": schema})

    return json.dumps(items, ensure_ascii=False, indent=2)


class BridgeSession:
    VERSION: str = __version__
    COMMIT: str = __commit__

    def __init__(
        self,
        llm: OpenAI,
        mcp: Client,
        mcp_tools: list[Any],
        *,
        temp: float = 0.2,
        max_tokens: int = 512,
        max_turns: int = 3,
        language: AgentLanguage = "en",
    ) -> None:
        self.llm = llm
        self.mcp = mcp
        self.mcp_tools = mcp_tools
        self.temp = temp
        self.max_tokens = max_tokens
        self.max_turns = max_turns
        self.language = language
        self.logger = logging.getLogger("mcp_bridge")

        self.f2m, _ = build_name_maps(mcp_tools)
        self.tools_block = build_tools_block(mcp_tools)
        self.sys_prompt = build_system_prompt(language=self.language, tools_block=self.tools_block)
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": self.sys_prompt}]

    def reset(self) -> None:
        self.messages = [{"role": "system", "content": self.sys_prompt}]
        self.logger.info("[SESSION] messages reset")

    async def handle_one_turn(
        self,
        user_text: str,
        *,
        model: str,
        debug: bool = False,
    ) -> Any:
        self.messages.append({"role": "user", "content": user_text})
        self.logger.debug("[LLM INPUT FULL]\n" + pretty_json(self.messages, limit=100000))

        assistant_text = ""
        turns_debug: list[dict[str, Any]] = []

        for turn in range(1, self.max_turns + 1):
            started = time.perf_counter()
            response = self.llm.chat.completions.create(
                model=model,
                messages=self.messages,
                tool_choice="none",
                temperature=self.temp,
                max_tokens=self.max_tokens,
            )
            elapsed = time.perf_counter() - started

            message = response.choices[0].message
            assistant_text = (message.content or "").strip()
            self.logger.info(
                "[LLM] response id: %s (%.2fs), finish_reason=%s",
                getattr(response, "id", "<no-id>"),
                elapsed,
                response.choices[0].finish_reason,
            )
            self.logger.debug("[LLM] assistant content:\n%s", message.content)

            if assistant_text:
                self.messages.append({"role": "assistant", "content": assistant_text})

            calls = extract_toolcalls_from_text(message.content or "")
            if calls:
                self.logger.info("[LLM] extracted tool_calls: %s", calls)

            turn_info: dict[str, Any] = {
                "turn_index": turn,
                "llm_raw": assistant_text,
                "tool_calls": calls,
                "tool_results": [],
            }

            if not calls:
                final_text = strip_toolcall_blocks(assistant_text) or assistant_text
                turns_debug.append(turn_info)
                if debug:
                    return {"final_answer": final_text, "turns": turns_debug}
                return final_text

            all_ok = True
            tool_results_turn: list[dict[str, Any]] = []

            for index, call in enumerate(calls, 1):
                func_name = call["name"]
                arguments = call.get("arguments", {})
                mcp_name = self.f2m.get(func_name)
                payload: dict[str, Any] = arguments

                self.logger.info(
                    "[TOOLCALL %s] func=%s args=%s",
                    index,
                    func_name,
                    json.dumps(arguments, ensure_ascii=False),
                )
                self.logger.info(
                    "[TOOLCALL %s] mapped LLM '%s' -> MCP '%s'",
                    index,
                    func_name,
                    mcp_name,
                )

                if not mcp_name:
                    tool_result: dict[str, Any] = {
                        "ok": False,
                        "error": f"unknown_tool_mapping:{func_name}",
                    }
                    all_ok = False
                else:
                    schema_obj = next(
                        (tool for tool in self.mcp_tools if _tool_name(tool) == mcp_name),
                        None,
                    )
                    if isinstance(schema_obj, dict):
                        schema_json = (
                            schema_obj.get("input_schema")
                            or schema_obj.get("inputSchema")
                            or {}
                        )
                    else:
                        schema_json = (
                            getattr(schema_obj, "input_schema", None)
                            or getattr(schema_obj, "inputSchema", None)
                            or {}
                        )
                    if hasattr(schema_json, "model_dump"):
                        schema_json = schema_json.model_dump()
                    if not isinstance(schema_json, dict):
                        schema_json = {}

                    payload = {"params": arguments} if requires_params_wrapper(schema_json) else arguments
                    try:
                        result = await self.mcp.call_tool(mcp_name, payload)
                        tool_result = getattr(result, "data", result)
                        self.logger.info(
                            "[TOOLCALL %s] MCP result:\n%s",
                            index,
                            pretty_json(tool_result),
                        )
                        if not (isinstance(tool_result, dict) and tool_result.get("ok", False)):
                            all_ok = False
                    except Exception as exc:
                        tool_result = {"ok": False, "error": str(exc)}
                        all_ok = False
                        self.logger.exception("[TOOLCALL %s] MCP ERROR: %s", index, exc)

                tool_results_turn.append(
                    {
                        "index": index,
                        "func_name": func_name,
                        "mcp_name": mcp_name,
                        "args": arguments,
                        "payload": payload,
                        "result": tool_result,
                    }
                )

                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": f"tc_{turn}_{index}",
                        "name": func_name,
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    }
                )

            turn_info["tool_results"] = tool_results_turn
            turns_debug.append(turn_info)

            if all_ok:
                self.logger.info(
                    "[BRIDGE] All tool calls OK; continuing loop for follow-up tool calls or final summary."
                )
                continue

            self.logger.info("[BRIDGE] Some tool calls failed; asking LLM for another plan.")

        final_text = strip_toolcall_blocks(assistant_text) or assistant_text
        self.logger.warning(
            "[CLIENT] Max turns reached without final non-tool answer; returning last assistant_text."
        )
        if debug:
            return {"final_answer": final_text, "turns": turns_debug}
        return final_text
