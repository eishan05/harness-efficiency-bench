"""Claude Code adapter."""

from __future__ import annotations

import json
from typing import Any

from .base import AdapterResult, AdapterRunContext, BaseAdapter
from .command import parse_jsonl_events, result_from_completed, run_command
from ..tracing import TraceEvent, model_call_event, tool_result_event


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
            "--no-session-persistence",
        ]
        completed = run_command(command, context)
        result = result_from_completed(completed)
        result.trace_events = self._parse_events(completed.stdout)
        result.metadata["trace_quality"] = "structured"
        return result

    @staticmethod
    def _parse_events(stdout: str) -> list[TraceEvent]:
        normalized: list[TraceEvent] = []
        model_call_positions: list[int] = []
        result_event: dict[str, Any] | None = None
        call_index = 0
        for raw in parse_jsonl_events(stdout):
            event_type = raw.get("type")
            usage = _event_usage(raw)
            if event_type != "result" and isinstance(usage, dict) and _usage_has_activity(usage):
                normalized.append(
                    model_call_event(
                        call_index=call_index,
                        input_tokens=_input_tokens(usage),
                        cached_input_tokens=_int_value(
                            usage.get("cache_read_input_tokens", usage.get("cached_input_tokens", 0))
                        ),
                        output_tokens=_int_value(usage.get("output_tokens", usage.get("completion_tokens", 0))),
                        reasoning_output_tokens=_int_value(usage.get("thinking_tokens", 0)),
                        cost_usd=_float_or_none(raw.get("total_cost_usd")),
                        metadata={"source": "claude_stream_json", "raw_event_type": event_type},
                    )
                )
                model_call_positions.append(len(normalized) - 1)
                call_index += 1

            for tool_result in _tool_results(raw):
                normalized.append(
                    tool_result_event(
                        name=tool_result["name"],
                        output=tool_result["output"],
                        call_index=(call_index - 1) if call_index else None,
                        metadata=tool_result["metadata"],
                    )
                )

            if event_type == "result":
                result_event = raw
            if event_type:
                normalized.append(TraceEvent(type="claude_event", data={"raw": raw}))
        if result_event:
            _apply_result_usage(normalized, model_call_positions, result_event, call_index)
        return normalized


def _event_usage(raw: dict[str, Any]) -> dict[str, Any] | None:
    usage = raw.get("usage")
    if isinstance(usage, dict):
        return usage
    message = raw.get("message")
    if isinstance(message, dict) and isinstance(message.get("usage"), dict):
        return message["usage"]
    return None


def _apply_result_usage(
    normalized: list[TraceEvent],
    model_call_positions: list[int],
    result_event: dict[str, Any],
    next_call_index: int,
) -> None:
    total_cost = _float_or_none(result_event.get("total_cost_usd"))
    if model_call_positions:
        if total_cost is None:
            return
        last_call = normalized[model_call_positions[-1]].data
        if last_call.get("cost_usd") is None:
            last_call["cost_usd"] = total_cost
            metadata = dict(last_call.get("metadata", {}))
            metadata["cost_source"] = "claude_result_total"
            last_call["metadata"] = metadata
        return

    usage = _event_usage(result_event)
    if not isinstance(usage, dict):
        return
    if not _usage_has_activity(usage) and not (total_cost and total_cost > 0):
        return
    normalized.append(
        model_call_event(
            call_index=next_call_index,
            input_tokens=_input_tokens(usage),
            cached_input_tokens=_int_value(usage.get("cache_read_input_tokens", usage.get("cached_input_tokens", 0))),
            output_tokens=_int_value(usage.get("output_tokens", usage.get("completion_tokens", 0))),
            reasoning_output_tokens=_int_value(usage.get("thinking_tokens", 0)),
            cost_usd=total_cost,
            metadata={"source": "claude_result_usage", "cost_source": "claude_result_total"},
        )
    )


def _usage_has_activity(usage: dict[str, Any]) -> bool:
    return (
        _input_tokens(usage)
        + _int_value(usage.get("output_tokens", usage.get("completion_tokens", 0)))
        + _int_value(usage.get("thinking_tokens", 0))
    ) > 0


def _input_tokens(usage: dict[str, Any]) -> int:
    base_input = _int_value(usage.get("input_tokens", usage.get("prompt_tokens", 0)))
    cache_read = _int_value(usage.get("cache_read_input_tokens", usage.get("cached_input_tokens", 0)))
    cache_creation = _cache_creation_tokens(usage)
    return base_input + cache_read + cache_creation


def _cache_creation_tokens(usage: dict[str, Any]) -> int:
    explicit = _int_value(usage.get("cache_creation_input_tokens", 0))
    if explicit:
        return explicit
    details = usage.get("cache_creation")
    if isinstance(details, dict):
        return sum(_int_value(value) for value in details.values())
    return 0


def _tool_results(raw: dict[str, Any]) -> list[dict[str, Any]]:
    message = raw.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    results: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "tool_result":
            continue
        output = _content_text(item.get("content", ""))
        if not output:
            continue
        tool_use_id = item.get("tool_use_id")
        results.append(
            {
                "name": str(tool_use_id or item.get("name") or "tool_result"),
                "output": output,
                "metadata": {
                    "source": "claude_stream_json",
                    "tool_use_id": tool_use_id,
                    "raw_event_type": raw.get("type"),
                },
            }
        )
    return results


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(part for part in (_content_text(item) for item in value) if part)
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if "content" in value:
            return _content_text(value["content"])
        return json.dumps(value, sort_keys=True)
    return "" if value is None else str(value)


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
