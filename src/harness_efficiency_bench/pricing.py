"""Provider-independent cost estimation."""

from __future__ import annotations

from .manifests import HarnessManifest
from .tracing import TraceEvent


def estimate_call_cost(call: dict[str, object], pricing: dict[str, float]) -> float | None:
    """Estimate model-call cost from per-million-token pricing.

    Supported pricing keys:
    - input_per_million
    - cached_input_per_million
    - output_per_million
    - reasoning_output_per_million
    """

    if not pricing:
        return None
    input_price = pricing.get("input_per_million")
    cached_price = pricing.get("cached_input_per_million", input_price)
    output_price = pricing.get("output_per_million")
    reasoning_price = pricing.get("reasoning_output_per_million", output_price)
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
    if reasoning_price is not None:
        cost += reasoning_tokens * reasoning_price / 1_000_000
    return cost


def apply_pricing(events: list[TraceEvent], harness: HarnessManifest) -> None:
    """Fill missing model-call cost fields in-place from harness pricing."""

    if not harness.pricing:
        return
    for event in events:
        if event.type != "model_call":
            continue
        if event.data.get("cost_usd") is not None:
            continue
        cost = estimate_call_cost(event.data, harness.pricing)
        if cost is not None:
            event.data["cost_usd"] = cost
            metadata = dict(event.data.get("metadata", {}))
            metadata["cost_source"] = "manifest_pricing"
            event.data["metadata"] = metadata

