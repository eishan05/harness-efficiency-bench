"""Claude Code adapter."""

from __future__ import annotations

from typing import Any

from .base import AdapterResult, AdapterRunContext, BaseAdapter
from .command import parse_jsonl_events, result_from_completed, run_command
from ..tracing import TraceEvent, model_call_event


class ClaudeCodeAdapter(BaseAdapter):
    name = "claude_code"

    def run(self, context: AdapterRunContext) -> AdapterResult:
        command = context.harness.command or [
            "claude",
            "--bare",
            "-p",
            "{prompt}",
            "--output-format",
            "stream-json",
            "--verbose",
        ]
        completed = run_command(command, context)
        result = result_from_completed(completed)
        result.trace_events = self._parse_events(completed.stdout)
        result.metadata["trace_quality"] = "structured"
        return result

    @staticmethod
    def _parse_events(stdout: str) -> list[TraceEvent]:
        normalized: list[TraceEvent] = []
        call_index = 0
        for raw in parse_jsonl_events(stdout):
            usage = raw.get("usage")
            if isinstance(usage, dict):
                normalized.append(
                    model_call_event(
                        call_index=call_index,
                        input_tokens=int(usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0) or 0),
                        cached_input_tokens=int(usage.get("cache_read_input_tokens", 0) or usage.get("cached_input_tokens", 0) or 0),
                        output_tokens=int(usage.get("output_tokens", 0) or usage.get("completion_tokens", 0) or 0),
                        reasoning_output_tokens=int(usage.get("thinking_tokens", 0) or 0),
                        cost_usd=_float_or_none(raw.get("total_cost_usd")),
                        metadata={"source": "claude_stream_json", "raw_type": raw.get("type")},
                    )
                )
                call_index += 1
            elif raw.get("type"):
                normalized.append(TraceEvent(type="claude_event", data={"raw": raw}))
        return normalized


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

