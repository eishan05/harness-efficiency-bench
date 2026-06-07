"""Metric extraction from normalized traces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .tokenization import count_tokens
from .tracing import TraceEvent


@dataclass(slots=True)
class MetricValue:
    value: float | int | None
    status: str = "full"
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "status": self.status,
            "details": self.details or {},
        }


def _model_calls(events: list[TraceEvent]) -> list[dict[str, Any]]:
    calls = [event.data for event in events if event.type == "model_call"]
    return sorted(calls, key=lambda item: int(item.get("call_index", len(calls))))


def startup_tax(events: list[TraceEvent], user_prompt_tokens: int) -> MetricValue:
    calls = _model_calls(events)
    if not calls:
        return MetricValue(None, "unsupported", {"reason": "no model_call events"})
    first_input = calls[0].get("input_tokens")
    if first_input is None:
        return MetricValue(None, "unsupported", {"reason": "first model call missing input_tokens"})
    return MetricValue(int(first_input) - user_prompt_tokens, "full")


def context_growth_rate(events: list[TraceEvent]) -> MetricValue:
    calls = _model_calls(events)
    points: list[tuple[float, float]] = []
    for index, call in enumerate(calls):
        input_tokens = call.get("input_tokens")
        if input_tokens is not None:
            points.append((float(call.get("call_index", index)), float(input_tokens)))
    if len(points) < 2:
        return MetricValue(None, "unsupported", {"reason": "need at least two model calls"})
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom == 0:
        return MetricValue(0.0, "full")
    slope = sum((x - x_mean) * (y - y_mean) for x, y in points) / denom
    return MetricValue(slope, "full", {"points": points})


def total_usage(events: list[TraceEvent]) -> dict[str, int | float]:
    usage = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "cost_usd": 0.0,
    }
    for call in _model_calls(events):
        usage["input_tokens"] += int(call.get("input_tokens", 0) or 0)
        usage["cached_input_tokens"] += int(call.get("cached_input_tokens", 0) or 0)
        usage["output_tokens"] += int(call.get("output_tokens", 0) or 0)
        usage["reasoning_output_tokens"] += int(call.get("reasoning_output_tokens", 0) or 0)
        usage["cost_usd"] += float(call.get("cost_usd", 0.0) or 0.0)
    return usage


def tool_output_retention_ratio(events: list[TraceEvent]) -> MetricValue:
    calls = [
        (pos, event.data)
        for pos, event in enumerate(events)
        if event.type == "model_call"
    ]
    tool_outputs = [
        (pos, str(event.data.get("output", "")))
        for pos, event in enumerate(events)
        if event.type == "tool_result" and event.data.get("output")
    ]
    if not calls:
        return MetricValue(None, "unsupported", {"reason": "no model_call events"})
    if not tool_outputs:
        return MetricValue(0.0, "full", {"reason": "no tool outputs"})
    if any("input_text" not in call for _, call in calls):
        return MetricValue(
            None,
            "unsupported",
            {"reason": "model_call input_text is required for exact retention"},
        )
    retained_tokens = 0
    total_input_tokens = 0
    matches: list[dict[str, Any]] = []
    for call_pos, call in calls:
        input_text = str(call.get("input_text", ""))
        input_tokens = int(call.get("input_tokens", 0) or count_tokens(input_text))
        total_input_tokens += input_tokens
        for output_pos, output in tool_outputs:
            if output_pos >= call_pos:
                continue
            if output and output in input_text:
                tokens = count_tokens(output)
                retained_tokens += tokens
                matches.append(
                    {
                        "call_index": call.get("call_index"),
                        "tool_event_pos": output_pos,
                        "tokens": tokens,
                    }
                )
    if total_input_tokens == 0:
        return MetricValue(None, "unsupported", {"reason": "zero total input tokens"})
    return MetricValue(
        retained_tokens / total_input_tokens,
        "full",
        {"retained_tokens": retained_tokens, "total_input_tokens": total_input_tokens, "matches": matches},
    )


def compute_run_metrics(events: list[TraceEvent], user_prompt_tokens: int) -> dict[str, Any]:
    usage = total_usage(events)
    return {
        "startup_tax": startup_tax(events, user_prompt_tokens).to_dict(),
        "context_growth_rate": context_growth_rate(events).to_dict(),
        "tool_output_retention_ratio": tool_output_retention_ratio(events).to_dict(),
        "usage": usage,
    }

