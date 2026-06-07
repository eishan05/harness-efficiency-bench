"""Docker-only adapter for black-box or semi-structured agent CLIs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import AdapterResult, AdapterRunContext, BaseAdapter
from .command import (
    missing_required_env,
    parse_jsonl_events,
    result_from_completed,
    run_command,
    run_version_check,
)
from ..isolation import isolation_backend
from ..tracing import TraceEvent, model_call_event, tool_result_event


class DockerAgentCliAdapter(BaseAdapter):
    name = "docker_agent_cli"

    def run(self, context: AdapterRunContext) -> AdapterResult:
        if isolation_backend(context.harness) != "docker":
            return AdapterResult(
                exit_code=2,
                stderr="docker_agent_cli adapter requires config.backend: docker\n",
                metadata={"trace_quality": "none", "bench_ready": False},
            )
        missing = missing_required_env(context)
        if missing:
            return AdapterResult(
                exit_code=2,
                stderr=f"missing required environment variables: {', '.join(missing)}\n",
                metadata={"trace_quality": "none", "bench_ready": False, "missing_required_env": missing},
            )
        if not context.harness.command:
            return AdapterResult(
                exit_code=2,
                stderr="docker_agent_cli adapter requires a command in the harness manifest\n",
                metadata={"trace_quality": "none", "bench_ready": False},
            )
        version_check = run_version_check(context)
        if not version_check.ok:
            return AdapterResult(
                exit_code=2,
                stderr=(
                    "CLI version preflight failed: "
                    f"expected {version_check.expected!r}, got {version_check.actual!r}\n"
                    f"{version_check.stderr}\n"
                ),
                metadata={"trace_quality": "none", "bench_ready": False, "version_check": version_check.to_metadata()},
            )

        completed = run_command(context.harness.command, context)
        result = result_from_completed(completed)
        native_events = parse_docker_agent_events(completed.stdout, context.harness.config)
        proxy_events = parse_proxy_trace_events(context.workspace, context.harness.config)
        parsed_events = native_events + proxy_events
        if parsed_events:
            result.trace_events = parsed_events
        result.metadata.update(
            {
                "trace_quality": "structured" if any(event.type == "model_call" for event in parsed_events) else "partial",
                "bench_ready": bool(context.harness.config.get("bench_ready", True)),
                "version_check": version_check.to_metadata(),
            }
        )
        if proxy_events:
            result.metadata["proxy_trace"] = "parsed"
        return result


def parse_docker_agent_events(stdout: str, config: dict[str, Any]) -> list[TraceEvent]:
    trace_config = _trace_config(config)
    parser = str(trace_config.get("parser", config.get("trace_parser", "generic_json")) or "none")
    if parser == "none":
        return []
    raw_events = _parse_json_or_jsonl(stdout)
    normalized: list[TraceEvent] = []
    call_index = 0
    for raw in raw_events:
        usage = _event_usage(raw)
        if usage and _usage_has_activity(usage):
            normalized.append(
                model_call_event(
                    call_index=call_index,
                    input_tokens=_input_tokens(usage),
                    cached_input_tokens=_int_value(
                        usage.get("cached_input_tokens", usage.get("cache_read_input_tokens", 0))
                    ),
                    output_tokens=_int_value(usage.get("output_tokens", usage.get("completion_tokens", 0))),
                    reasoning_output_tokens=_int_value(
                        usage.get("reasoning_output_tokens", usage.get("thinking_tokens", 0))
                    ),
                    cost_usd=_cost_usd(raw, usage),
                    metadata={"source": parser, "raw_event_type": raw.get("type") or raw.get("role")},
                )
            )
            call_index += 1
        tool_result = _tool_result(raw, parser)
        if tool_result:
            normalized.append(tool_result)
        event_type = raw.get("type") or raw.get("role")
        if event_type:
            normalized.append(TraceEvent(type="agent_cli_event", data={"raw": raw, "parser": parser}))
    return normalized


def parse_proxy_trace_events(workspace: Path, config: dict[str, Any]) -> list[TraceEvent]:
    trace_config = _trace_config(config)
    relative_path = trace_config.get("litellm_log_path") or config.get("litellm_log_path")
    if not relative_path:
        return []
    trace_path = workspace / str(relative_path).lstrip("/")
    if not trace_path.exists():
        return []
    events: list[TraceEvent] = []
    call_index = 0
    for raw in _parse_json_or_jsonl(trace_path.read_text(encoding="utf-8")):
        usage = _event_usage(raw)
        if not usage or not _usage_has_activity(usage):
            continue
        events.append(
            model_call_event(
                call_index=call_index,
                input_tokens=_input_tokens(usage),
                cached_input_tokens=_int_value(usage.get("cached_input_tokens", usage.get("cache_read_input_tokens", 0))),
                output_tokens=_int_value(usage.get("output_tokens", usage.get("completion_tokens", 0))),
                reasoning_output_tokens=_int_value(usage.get("reasoning_output_tokens", usage.get("thinking_tokens", 0))),
                cost_usd=_cost_usd(raw, usage),
                metadata={"source": "litellm_proxy", "model": raw.get("model")},
            )
        )
        call_index += 1
    return events


def _trace_config(config: dict[str, Any]) -> dict[str, Any]:
    trace = config.get("trace")
    return trace if isinstance(trace, dict) else {}


def _parse_json_or_jsonl(text: str) -> list[dict[str, Any]]:
    stripped = text.strip()
    if not stripped:
        return []
    try:
        raw = json.loads(stripped)
    except json.JSONDecodeError:
        return parse_jsonl_events(text)
    return _flatten_json_payload(raw)


def _flatten_json_payload(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        items = [raw]
        for key in ("events", "messages", "items"):
            value = raw.get(key)
            if isinstance(value, list):
                items.extend(item for item in value if isinstance(item, dict))
        return items
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def _event_usage(raw: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[Any] = [
        raw.get("usage"),
        raw.get("token_usage"),
        raw.get("metrics", {}).get("usage") if isinstance(raw.get("metrics"), dict) else None,
        raw.get("message", {}).get("usage") if isinstance(raw.get("message"), dict) else None,
        raw.get("response", {}).get("usage") if isinstance(raw.get("response"), dict) else None,
        raw.get("metadata", {}).get("usage") if isinstance(raw.get("metadata"), dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return None


def _usage_has_activity(usage: dict[str, Any]) -> bool:
    return (
        _input_tokens(usage)
        + _int_value(usage.get("output_tokens", usage.get("completion_tokens", 0)))
        + _int_value(usage.get("reasoning_output_tokens", usage.get("thinking_tokens", 0)))
    ) > 0


def _input_tokens(usage: dict[str, Any]) -> int:
    base_input = _int_value(usage.get("input_tokens", usage.get("prompt_tokens", 0)))
    cache_read = _int_value(usage.get("cache_read_input_tokens", usage.get("cached_input_tokens", 0)))
    cache_creation = _int_value(usage.get("cache_creation_input_tokens", 0))
    return base_input + cache_read + cache_creation


def _tool_result(raw: dict[str, Any], parser: str) -> TraceEvent | None:
    role = raw.get("role")
    event_type = raw.get("type")
    if role != "tool" and event_type not in {"tool_result", "tool"}:
        return None
    output = _content_text(raw.get("content", raw.get("output", raw.get("result", ""))))
    if not output:
        return None
    return tool_result_event(
        name=str(raw.get("name") or raw.get("tool_name") or raw.get("tool_call_id") or "tool"),
        output=output,
        metadata={"source": parser, "raw_event_type": event_type or role},
    )


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


def _cost_usd(raw: dict[str, Any], usage: dict[str, Any]) -> float | None:
    candidates: list[Any] = [
        raw.get("cost_usd"),
        raw.get("total_cost_usd"),
        raw.get("response_cost"),
        raw.get("cost"),
        usage.get("cost_usd"),
        usage.get("total_cost_usd"),
        usage.get("response_cost"),
        raw.get("metadata", {}).get("cost_usd") if isinstance(raw.get("metadata"), dict) else None,
        raw.get("metadata", {}).get("response_cost") if isinstance(raw.get("metadata"), dict) else None,
    ]
    for candidate in candidates:
        value = _float_or_none(candidate)
        if value is not None:
            return value
    return None


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
