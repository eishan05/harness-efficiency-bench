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
    if _is_aggregate_model_call(calls[0]):
        return MetricValue(
            int(first_input) - user_prompt_tokens,
            "partial",
            {"reason": "model_call input_tokens are aggregate run usage, not first-call usage"},
        )
    return MetricValue(int(first_input) - user_prompt_tokens, "full")


def context_growth_rate(events: list[TraceEvent]) -> MetricValue:
    calls = _model_calls(events)
    points: list[tuple[float, float]] = []
    for index, call in enumerate(calls):
        if _is_aggregate_model_call(call):
            continue
        input_tokens = call.get("input_tokens")
        if input_tokens is not None:
            points.append((float(call.get("call_index", index)), float(input_tokens)))
    if len(points) < 2:
        return MetricValue(None, "unsupported", {"reason": "need at least two non-aggregate model calls"})
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom == 0:
        return MetricValue(0.0, "full")
    slope = sum((x - x_mean) * (y - y_mean) for x, y in points) / denom
    return MetricValue(slope, "full", {"points": points})


def total_usage(events: list[TraceEvent]) -> dict[str, int | float | bool]:
    usage = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "token_cost": 0,
        "cost_usd": 0.0,
        "cost_available": False,
    }
    calls = _model_calls(events)
    cost_available = bool(calls)
    for call in calls:
        usage["input_tokens"] += int(call.get("input_tokens", 0) or 0)
        usage["cached_input_tokens"] += int(call.get("cached_input_tokens", 0) or 0)
        usage["output_tokens"] += int(call.get("output_tokens", 0) or 0)
        usage["reasoning_output_tokens"] += int(call.get("reasoning_output_tokens", 0) or 0)
        if call.get("cost_usd") is None:
            cost_available = False
        else:
            usage["cost_usd"] += float(call.get("cost_usd", 0.0) or 0.0)
    usage["token_cost"] = usage_token_cost(usage)
    usage["cost_available"] = cost_available
    return usage


def usage_token_cost(usage: dict[str, Any]) -> int:
    return (
        int(usage.get("input_tokens", 0) or 0)
        + int(usage.get("output_tokens", 0) or 0)
        + int(usage.get("reasoning_output_tokens", 0) or 0)
    )


def _is_aggregate_model_call(call: dict[str, Any]) -> bool:
    metadata = call.get("metadata")
    return isinstance(metadata, dict) and bool(metadata.get("aggregate"))


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


def research_metric_coverage(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "startup_tax": _run_metric_coverage(
            results,
            "startup_tax",
            "full requires structured non-aggregate model_call events with first-call input_tokens",
        ),
        "context_growth_rate": _run_metric_coverage(
            results,
            "context_growth_rate",
            "full requires at least two non-aggregate model_call events with input_tokens per run",
        ),
        "solve_efficiency": _solve_efficiency_coverage(results),
    }


def _run_metric_coverage(results: list[dict[str, Any]], metric_name: str, requirement: str) -> dict[str, Any]:
    statuses = [
        str(item.get("metrics", {}).get(metric_name, {}).get("status", "unsupported"))
        for item in results
    ]
    full = statuses.count("full")
    partial = statuses.count("partial")
    unsupported = len(statuses) - full - partial
    if not statuses:
        status = "unsupported"
    elif full == len(statuses):
        status = "full"
    elif full or partial:
        status = "partial"
    else:
        status = "unsupported"
    return {
        "status": status,
        "runs_full": full,
        "runs_partial": partial,
        "runs_unsupported": unsupported,
        "requirement": requirement,
    }


def _solve_efficiency_coverage(results: list[dict[str, Any]]) -> dict[str, Any]:
    runs_with_token_usage = 0
    for item in results:
        usage = item.get("metrics", {}).get("usage", {})
        if usage_token_cost(usage) > 0:
            runs_with_token_usage += 1
    if not results:
        status = "unsupported"
    elif runs_with_token_usage == len(results):
        status = "full"
    elif runs_with_token_usage:
        status = "partial"
    else:
        status = "unsupported"
    return {
        "status": status,
        "runs_with_token_cost": runs_with_token_usage,
        "runs_total": len(results),
        "requirement": "full requires token usage for every run",
    }


def _context_bloat_coverage(results: list[dict[str, Any]]) -> dict[str, Any]:
    perturbations = {str(item.get("perturbation_id") or "base") for item in results}
    has_base = "base" in perturbations
    non_base = sorted(item for item in perturbations if item != "base")
    if has_base and non_base:
        status = "full"
    elif non_base:
        status = "partial"
    else:
        status = "unsupported"
    return {
        "status": status,
        "perturbations": sorted(perturbations),
        "requirement": "full requires base runs and at least one controlled context perturbation",
    }
