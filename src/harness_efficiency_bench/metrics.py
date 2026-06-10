"""Metric extraction from normalized traces."""

from __future__ import annotations

import statistics
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


# A leading call is treated as an auxiliary preflight request (for example title
# generation) when it is this much smaller than the early calls that follow it
# and its overhead beyond the rendered task prompt stays under the cap. Without
# this, CLIs that send a tiny helper request first (Opencode, Kilo) report that
# request as the task-first call, which understates startup tax and contaminates
# the context-growth slope with the jump to the real first task call.
AUXILIARY_PREFLIGHT_MAX_INPUT_RATIO = 0.25
AUXILIARY_PREFLIGHT_MAX_OVERHEAD_TOKENS = 2000
AUXILIARY_PREFLIGHT_LOOKAHEAD_CALLS = 3


def _auxiliary_preflight_positions(calls: list[dict[str, Any]], user_prompt_tokens: int) -> set[int]:
    positions: set[int] = set()
    for position in range(len(calls) - 1):
        input_tokens = calls[position].get("input_tokens")
        if input_tokens is None:
            break
        input_token_count = int(input_tokens)
        if input_token_count > user_prompt_tokens + AUXILIARY_PREFLIGHT_MAX_OVERHEAD_TOKENS:
            break
        following = [
            int(call["input_tokens"])
            for call in calls[position + 1 : position + 1 + AUXILIARY_PREFLIGHT_LOOKAHEAD_CALLS]
            if call.get("input_tokens") is not None
        ]
        if not following or input_token_count > AUXILIARY_PREFLIGHT_MAX_INPUT_RATIO * max(following):
            break
        positions.add(position)
    return positions


def _auxiliary_preflight_call_indices(calls: list[dict[str, Any]], positions: set[int]) -> list[int]:
    return [int(calls[position].get("call_index", position)) for position in sorted(positions)]


def _call_model(call: dict[str, Any]) -> str | None:
    metadata = call.get("metadata")
    if isinstance(metadata, dict):
        model = metadata.get("model")
        if model:
            return str(model)
    return None


def _model_mismatch_positions(calls: list[dict[str, Any]]) -> set[int]:
    """Positions of calls billed to a different model than the run's dominant
    model (the model carrying the most input tokens). Some CLIs route helper
    requests such as title generation to a smaller model (Opencode and Kilo
    bill theirs to Claude Haiku); those calls are not part of the task
    conversation, so they are excluded from task-first startup tax and from
    the context-growth fit. They still count toward solve-efficiency totals.
    Note this assumes a single-model task conversation: a harness that
    deliberately splits the task across models would need per-model fits."""
    totals: dict[str, int] = {}
    for call in calls:
        model = _call_model(call)
        if model is None:
            continue
        totals[model] = totals.get(model, 0) + int(call.get("input_tokens", 0) or 0)
    if len(totals) < 2:
        return set()
    dominant = max(totals, key=lambda model: (totals[model], model))
    return {
        position
        for position, call in enumerate(calls)
        if _call_model(call) is not None and _call_model(call) != dominant
    }


# Conversation context grows roughly monotonically within one agent thread.
# Some CLIs interleave a separate sub-conversation mid-run (Kilo and Opencode
# both do), which shows up as the per-call input dropping sharply and later
# returning to the main thread's level. Fitting one slope across interleaved
# threads inflates the growth rate, so calls are segmented into monotone
# threads and the slope is fit on the dominant one. The tolerance absorbs
# small within-thread dips from prompt trimming or token-count jitter.
CONTEXT_THREAD_JITTER_RATIO = 0.05
CONTEXT_THREAD_JITTER_MIN_TOKENS = 512


def _segment_context_threads(values: list[tuple[int, float]]) -> list[list[tuple[int, float]]]:
    threads: list[list[tuple[int, float]]] = []
    for call_index, input_tokens in values:
        best: list[tuple[int, float]] | None = None
        for thread in threads:
            tail = thread[-1][1]
            tolerance = max(tail * CONTEXT_THREAD_JITTER_RATIO, CONTEXT_THREAD_JITTER_MIN_TOKENS)
            if tail <= input_tokens + tolerance and (best is None or tail > best[-1][1]):
                best = thread
        if best is None:
            threads.append([(call_index, input_tokens)])
        else:
            best.append((call_index, input_tokens))
    return threads


def startup_tax(events: list[TraceEvent], user_prompt_tokens: int) -> MetricValue:
    all_calls = _model_calls(events)
    calls = _per_call_model_calls(all_calls)
    if not calls:
        if not all_calls:
            return MetricValue(None, "unsupported", {"reason": "no model_call events"})
        first_input = all_calls[0].get("input_tokens")
        if first_input is None:
            return MetricValue(None, "unsupported", {"reason": "first model call missing input_tokens"})
        if int(first_input) < user_prompt_tokens:
            return MetricValue(
                None,
                "unsupported",
                {"reason": _input_below_prompt_reason(first_input, user_prompt_tokens)},
            )
        return MetricValue(
            int(first_input) - user_prompt_tokens,
            "partial",
            {"reason": "model_call input_tokens are aggregate run usage, not first-call usage"},
        )
    provider_first = calls[0]
    task_candidates = [call for call in calls if not _is_preflight_model_call(call)]
    auxiliary_positions = _auxiliary_preflight_positions(task_candidates, user_prompt_tokens)
    mismatch_positions = _model_mismatch_positions(task_candidates)
    excluded_positions = auxiliary_positions | mismatch_positions
    task_calls = [call for position, call in enumerate(task_candidates) if position not in excluded_positions]
    provider_tax = _call_startup_tax(provider_first, user_prompt_tokens)
    if provider_tax is None:
        return MetricValue(
            None,
            "unsupported",
            {"reason": _startup_tax_unsupported_reason(provider_first, user_prompt_tokens, "provider-first")},
        )
    details: dict[str, Any] = {
        "provider_first_startup_tax": provider_tax,
        "provider_first_call_index": provider_first.get("call_index"),
    }
    if auxiliary_positions:
        details["auxiliary_preflight_call_indices"] = _auxiliary_preflight_call_indices(
            task_candidates, auxiliary_positions
        )
    if mismatch_positions:
        details["model_mismatch_call_indices"] = _auxiliary_preflight_call_indices(
            task_candidates, mismatch_positions
        )
    if not task_calls:
        return MetricValue(
            provider_tax,
            "partial",
            {**details, "reason": "no non-preflight task model_call events"},
        )
    task_first = task_calls[0]
    task_tax = _call_startup_tax(task_first, user_prompt_tokens)
    if task_tax is None:
        return MetricValue(
            None,
            "unsupported",
            {"reason": _startup_tax_unsupported_reason(task_first, user_prompt_tokens, "task-first")},
        )
    details.update(
        {
            "task_first_startup_tax": task_tax,
            "task_first_call_index": task_first.get("call_index"),
        }
    )
    if provider_first is task_first:
        return MetricValue(provider_tax, "full", details)
    details["composition"] = "provider_first_startup_tax + task_first_startup_tax"
    return MetricValue(provider_tax + task_tax, "full", details)


def context_growth_rate(events: list[TraceEvent], user_prompt_tokens: int = 0) -> MetricValue:
    calls = _model_calls(events)
    candidates = [call for call in _per_call_model_calls(calls) if not _is_preflight_model_call(call)]
    auxiliary_positions = _auxiliary_preflight_positions(candidates, user_prompt_tokens)
    mismatch_positions = _model_mismatch_positions(candidates)
    excluded_positions = auxiliary_positions | mismatch_positions
    measured: list[tuple[int, float]] = []
    for position, call in enumerate(candidates):
        if position in excluded_positions:
            continue
        input_tokens = call.get("input_tokens")
        if input_tokens is not None:
            measured.append((int(call.get("call_index", position)), float(input_tokens)))
    if len(measured) < 2:
        return MetricValue(None, "unsupported", {"reason": "need at least two non-aggregate non-preflight model calls"})
    threads = _segment_context_threads(measured)
    dominant = max(threads, key=lambda thread: (len(thread), thread[-1][1]))
    fitted = dominant if len(dominant) >= 2 else measured
    # x is the call's turn position within its thread, so the slope reads as
    # input-token growth per turn of the dominant conversation.
    points = [(float(position), input_tokens) for position, (_, input_tokens) in enumerate(fitted)]
    details: dict[str, Any] = {
        "points": points,
        "call_indices": [call_index for call_index, _ in fitted],
    }
    if len(threads) > 1 and fitted is dominant:
        details["context_thread_sizes"] = sorted((len(thread) for thread in threads), reverse=True)
        details["excluded_call_indices"] = sorted(
            call_index
            for thread in threads
            if thread is not dominant
            for call_index, _ in thread
        )
    if auxiliary_positions:
        details["auxiliary_preflight_call_indices"] = _auxiliary_preflight_call_indices(
            candidates, auxiliary_positions
        )
    if mismatch_positions:
        details["model_mismatch_call_indices"] = _auxiliary_preflight_call_indices(
            candidates, mismatch_positions
        )
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom == 0:
        return MetricValue(0.0, "full")
    slope = sum((x - x_mean) * (y - y_mean) for x, y in points) / denom
    deltas = [ys[index + 1] - ys[index] for index in range(len(ys) - 1)]
    if deltas:
        median_delta = statistics.median(deltas)
        details["median_adjacent_delta"] = median_delta
        if slope * median_delta > 0:
            details["slope_median_delta_ratio"] = max(abs(slope), abs(median_delta)) / min(
                abs(slope), abs(median_delta)
            )
        if _slope_diverges_from_median_delta(slope, median_delta):
            details["slope_median_divergence"] = True
    return MetricValue(slope, "full", details)


# The fitted slope and the median adjacent per-call delta should roughly agree
# on a monotone thread. A divergence beyond this ratio means a few extreme
# points dominate the fit — historically the signature of an aggregate summary
# event or interleaved thread that slipped past structural detection — so the
# run is flagged for inspection. Small-magnitude disagreements are noise.
CONTEXT_GROWTH_DIVERGENCE_RATIO = 2.0
CONTEXT_GROWTH_DIVERGENCE_MIN_TOKENS = 64.0


def _slope_diverges_from_median_delta(slope: float, median_delta: float) -> bool:
    magnitude = max(abs(slope), abs(median_delta))
    if magnitude < CONTEXT_GROWTH_DIVERGENCE_MIN_TOKENS:
        return False
    if slope * median_delta <= 0:
        return True
    return magnitude / min(abs(slope), abs(median_delta)) > CONTEXT_GROWTH_DIVERGENCE_RATIO


def total_usage(events: list[TraceEvent]) -> dict[str, Any]:
    usage = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "reasoning_tokens_in_output": 0,
        "token_cost": 0,
        "cost_usd": 0.0,
        "cost_available": False,
    }
    all_calls = _model_calls(events)
    summary_positions = _cumulative_summary_positions(all_calls)
    per_call = [
        call
        for position, call in enumerate(all_calls)
        if position not in summary_positions and not _is_aggregate_model_call(call)
    ]
    summary_calls = [
        call
        for position, call in enumerate(all_calls)
        if position in summary_positions or _is_aggregate_model_call(call)
    ]
    # Aggregate/summary calls repeat usage already counted by per-call events,
    # so they only stand in for totals when no per-call usage exists.
    calls = per_call or all_calls
    cost_available = bool(calls)
    by_model: dict[str, dict[str, int]] = {}
    for call in calls:
        usage["input_tokens"] += int(call.get("input_tokens", 0) or 0)
        usage["cached_input_tokens"] += int(call.get("cached_input_tokens", 0) or 0)
        usage["output_tokens"] += int(call.get("output_tokens", 0) or 0)
        reasoning_tokens = int(call.get("reasoning_output_tokens", 0) or 0)
        usage["reasoning_output_tokens"] += reasoning_tokens
        if call.get("reasoning_in_output"):
            usage["reasoning_tokens_in_output"] += reasoning_tokens
        if call.get("cost_usd") is None:
            cost_available = False
        else:
            usage["cost_usd"] += float(call.get("cost_usd", 0.0) or 0.0)
        model = _call_model(call)
        if model is not None:
            model_bucket = by_model.setdefault(model, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
            model_bucket["calls"] += 1
            model_bucket["input_tokens"] += int(call.get("input_tokens", 0) or 0)
            model_bucket["output_tokens"] += int(call.get("output_tokens", 0) or 0)
    if not cost_available and per_call and summary_calls:
        if all(call.get("cost_usd") is not None for call in summary_calls):
            usage["cost_usd"] = sum(float(call.get("cost_usd") or 0.0) for call in summary_calls)
            cost_available = True
    usage["token_cost"] = usage_token_cost(usage)
    usage["token_cost_cache_discounted"] = usage_token_cost_cache_discounted(usage)
    usage["cost_available"] = cost_available
    if by_model:
        usage["by_model"] = by_model
    return usage


def usage_token_cost(usage: dict[str, Any]) -> int:
    # Reasoning tokens reported as a breakdown of completion/output tokens
    # (OpenAI-compatible completion_tokens_details) are already inside
    # output_tokens; only separately billed reasoning tokens are additive.
    reasoning_tokens = int(usage.get("reasoning_output_tokens", 0) or 0)
    nested_reasoning_tokens = int(usage.get("reasoning_tokens_in_output", 0) or 0)
    return (
        int(usage.get("input_tokens", 0) or 0)
        + int(usage.get("output_tokens", 0) or 0)
        + max(reasoning_tokens - nested_reasoning_tokens, 0)
    )


# Cache reads are billed at roughly a tenth of the uncached input price by
# most providers, so the cache-discounted token cost weights cached input
# tokens at 0.1 instead of dropping them entirely.
CACHED_INPUT_TOKEN_WEIGHT = 0.1


def usage_token_cost_cache_discounted(usage: dict[str, Any]) -> float:
    # cached_input_tokens is a subset of input_tokens (the OpenAI/OpenRouter
    # convention, matching pricing.estimate_call_cost), so the discount
    # subtracts the non-billed share of the cached portion.
    cached_tokens = min(
        int(usage.get("cached_input_tokens", 0) or 0),
        int(usage.get("input_tokens", 0) or 0),
    )
    return usage_token_cost(usage) - cached_tokens * (1 - CACHED_INPUT_TOKEN_WEIGHT)


def _is_aggregate_model_call(call: dict[str, Any]) -> bool:
    metadata = call.get("metadata")
    return isinstance(metadata, dict) and bool(metadata.get("aggregate"))


def _cumulative_summary_positions(calls: list[dict[str, Any]]) -> set[int]:
    """Positions of calls whose usage repeats the cumulative totals of the
    calls before them (for example Qwen Code's final result event). Adapters
    mark these as aggregate for new runs; detecting them here as well keeps
    metrics correct when recomputing from traces recorded before that."""
    positions: set[int] = set()
    running_input = 0
    running_output = 0
    counted = 0
    for position, call in enumerate(calls):
        if _is_aggregate_model_call(call):
            continue
        input_tokens = int(call.get("input_tokens", 0) or 0)
        output_tokens = int(call.get("output_tokens", 0) or 0)
        if counted >= 2 and running_input > 0 and input_tokens == running_input and output_tokens == running_output:
            positions.add(position)
            continue
        running_input += input_tokens
        running_output += output_tokens
        counted += 1
    return positions


def _per_call_model_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary_positions = _cumulative_summary_positions(calls)
    return [
        call
        for position, call in enumerate(calls)
        if position not in summary_positions and not _is_aggregate_model_call(call)
    ]


def _is_preflight_model_call(call: dict[str, Any]) -> bool:
    metadata = call.get("metadata")
    return isinstance(metadata, dict) and bool(metadata.get("preflight"))


def _call_startup_tax(call: dict[str, Any], user_prompt_tokens: int) -> int | None:
    input_tokens = call.get("input_tokens")
    if input_tokens is None:
        return None
    input_token_count = int(input_tokens)
    if input_token_count < user_prompt_tokens:
        return None
    return input_token_count - user_prompt_tokens


def _startup_tax_unsupported_reason(call: dict[str, Any], user_prompt_tokens: int, label: str) -> str:
    input_tokens = call.get("input_tokens")
    if input_tokens is None:
        return f"{label} model call missing input_tokens"
    if int(input_tokens) < user_prompt_tokens:
        return _input_below_prompt_reason(input_tokens, user_prompt_tokens)
    return f"{label} model call startup tax unavailable"


def _input_below_prompt_reason(input_tokens: Any, user_prompt_tokens: int) -> str:
    return (
        "model_call input_tokens is below the benchmark prompt token estimate "
        f"({int(input_tokens)} < {user_prompt_tokens}); startup tax is not comparable"
    )


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
        "context_growth_rate": context_growth_rate(events, user_prompt_tokens).to_dict(),
        "tool_output_retention_ratio": tool_output_retention_ratio(events).to_dict(),
        "usage": usage,
    }


def research_metric_coverage(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "startup_tax": _run_metric_coverage(
            results,
            "startup_tax",
            "full requires structured non-aggregate model_call events with provider-first and task-first input_tokens",
        ),
        "context_growth_rate": _run_metric_coverage(
            results,
            "context_growth_rate",
            "full requires at least two non-aggregate non-preflight model_call events with input_tokens per run",
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
