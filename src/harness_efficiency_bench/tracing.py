"""Normalized trace events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class TraceEvent:
    type: str
    timestamp: str = field(default_factory=utc_now)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "timestamp": self.timestamp,
            **self.data,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TraceEvent":
        raw = dict(raw)
        event_type = str(raw.pop("type"))
        timestamp = str(raw.pop("timestamp", utc_now()))
        return cls(type=event_type, timestamp=timestamp, data=raw)


def model_call_event(
    *,
    call_index: int,
    input_tokens: int,
    output_tokens: int = 0,
    input_text: str | None = None,
    cached_input_tokens: int = 0,
    reasoning_output_tokens: int = 0,
    reasoning_in_output: bool = False,
    cost_usd: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> TraceEvent:
    data: dict[str, Any] = {
        "call_index": call_index,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
    }
    if reasoning_in_output:
        data["reasoning_in_output"] = True
    if input_text is not None:
        data["input_text"] = input_text
    if cost_usd is not None:
        data["cost_usd"] = cost_usd
    if metadata:
        data["metadata"] = metadata
    return TraceEvent(type="model_call", data=data)


def tool_result_event(
    *,
    name: str,
    output: str,
    call_index: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> TraceEvent:
    data: dict[str, Any] = {
        "name": name,
        "output": output,
    }
    if call_index is not None:
        data["call_index"] = call_index
    if metadata:
        data["metadata"] = metadata
    return TraceEvent(type="tool_result", data=data)

