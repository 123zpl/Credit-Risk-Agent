"""Tool 调用追踪：通过 LangChain callback 收集 Agent 工具调用。"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

_tool_traces: ContextVar[list[dict]] = ContextVar("tool_traces", default=[])


def reset_tool_traces() -> None:
    _tool_traces.set([])


def get_tool_traces() -> list[dict]:
    return list(_tool_traces.get())


def tool_trace_log_entries(agent: str, step: int, traces: list[dict]) -> list[dict]:
    """将 tool traces 转为 execution_log 条目。"""
    entries: list[dict] = []
    for idx, trace in enumerate(traces):
        entries.append({
            "agent": agent,
            "step": step,
            "action": f"tool:{trace.get('tool', 'unknown')}",
            "action_input": str(trace.get("input", ""))[:1000],
            "result": str(trace.get("output", ""))[:500],
            "latency_ms": trace.get("latency_ms", 0),
            "tool_index": idx,
        })
    return entries


class ToolTraceCallback(BaseCallbackHandler):
    """记录 on_tool_end 事件到 context-local buffer。"""

    def on_tool_end(self, output: Any, **kwargs: Any) -> None:
        traces = _tool_traces.get()
        serialized = kwargs.get("serialized") or {}
        tool_name = kwargs.get("name") or ""
        if isinstance(serialized, dict):
            tool_name = tool_name or serialized.get("name") or serialized.get("id") or ""
        tool_input = ""
        if kwargs.get("inputs") is not None:
            tool_input = str(kwargs["inputs"])
        elif kwargs.get("input") is not None:
            tool_input = str(kwargs["input"])

        traces.append({
            "tool": tool_name or "unknown_tool",
            "input": tool_input[:2000],
            "output": str(output)[:2000],
            "latency_ms": 0,
        })
        _tool_traces.set(traces)


def merge_agent_config(base: dict) -> dict:
    """在 agent invoke config 中注入 ToolTraceCallback。"""
    cfg = dict(base)
    callbacks = list(cfg.get("callbacks") or [])
    callbacks.append(ToolTraceCallback())
    cfg["callbacks"] = callbacks
    return cfg
