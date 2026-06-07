"""Provider-independent cost estimation."""

from __future__ import annotations

from typing import Any

from .manifests import HarnessManifest
from .tracing import TraceEvent


def estimate_call_cost(
    call: dict[str, object],
    pricing: dict[str, float],
    *,
    long_context: bool | None = None,
) -> float | None:
    """Estimate model-call cost from per-million-token pricing.

    Supported pricing keys:
    - input_per_million
    - cached_input_per_million
    - output_per_million
    - reasoning_output_per_million
    - long_context_threshold_tokens
    - long_context_input_per_million
    - long_context_cached_input_per_million
    - long_context_output_per_million
    """

    if not pricing:
        return None
    effective_pricing = _effective_pricing(call, pricing, long_context=long_context)
    input_price = effective_pricing.get("input_per_million")
    cached_price = effective_pricing.get("cached_input_per_million", input_price)
    output_price = effective_pricing.get("output_per_million")
    reasoning_price = effective_pricing.get("reasoning_output_per_million", output_price)
    if input_price is None and output_price is None and cached_price is None and reasoning_price is None:
        return None

    input_tokens = int(call.get("input_tokens", 0) or 0)
    cached_tokens = int(call.get("cached_input_tokens", 0) or 0)
    uncached_tokens = max(input_tokens - cached_tokens, 0)
    output_tokens = int(call.get("output_tokens", 0) or 0)
    reasoning_tokens = int(call.get("reasoning_output_tokens", 0) or 0)

    cost = 0.0
    if input_price is not None:
        cost += uncached_tokens * input_price / 1_000_000
    if cached_price is not None:
        cost += cached_tokens * cached_price / 1_000_000
    if output_price is not None:
        cost += output_tokens * output_price / 1_000_000
    reasoning_is_additive = bool(pricing.get("reasoning_output_tokens_are_additive", 0.0))
    if reasoning_price is not None and (reasoning_is_additive or output_tokens == 0):
        cost += reasoning_tokens * reasoning_price / 1_000_000
    return cost


def _effective_pricing(
    call: dict[str, object],
    pricing: dict[str, float],
    *,
    long_context: bool | None,
) -> dict[str, float]:
    input_tokens = int(call.get("input_tokens", 0) or 0)
    threshold = pricing.get("long_context_threshold_tokens")
    use_long_context = bool(
        long_context if long_context is not None else threshold is not None and input_tokens > threshold
    )
    if not use_long_context:
        return dict(pricing)
    effective = dict(pricing)
    replacements = {
        "input_per_million": "long_context_input_per_million",
        "cached_input_per_million": "long_context_cached_input_per_million",
        "output_per_million": "long_context_output_per_million",
        "reasoning_output_per_million": "long_context_reasoning_output_per_million",
    }
    for normal_key, long_key in replacements.items():
        if long_key in pricing:
            effective[normal_key] = pricing[long_key]
    return effective


def _run_uses_long_context(calls: list[dict[str, Any]], pricing: dict[str, float]) -> bool:
    threshold = pricing.get("long_context_threshold_tokens")
    if threshold is None:
        return False
    return any(int(call.get("input_tokens", 0) or 0) > threshold for call in calls)


def apply_pricing(events: list[TraceEvent], harness: HarnessManifest) -> None:
    """Fill missing model-call cost fields in-place from harness pricing."""

    if not harness.pricing:
        return
    calls = [event.data for event in events if event.type == "model_call"]
    long_context = _run_uses_long_context(calls, harness.pricing)
    for event in events:
        if event.type != "model_call":
            continue
        if event.data.get("cost_usd") is not None:
            continue
        cost = estimate_call_cost(event.data, harness.pricing, long_context=long_context)
        if cost is not None:
            event.data["cost_usd"] = cost
            metadata = dict(event.data.get("metadata", {}))
            metadata["cost_source"] = "manifest_pricing"
            metadata["pricing_context"] = "long" if long_context else "short"
            event.data["metadata"] = metadata
