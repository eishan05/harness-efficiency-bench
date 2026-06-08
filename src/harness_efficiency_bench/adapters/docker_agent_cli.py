"""Docker-only adapter for black-box or semi-structured agent CLIs."""

from __future__ import annotations

import json
import re
from dataclasses import replace
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
from ..usage_proxy import proxy_from_config


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

        proxy = proxy_from_config(context.workspace, context.harness.config)
        active_context = context
        proxy_metadata: dict[str, Any] = {}
        if proxy is not None:
            proxy.start()
            active_context = _with_proxy_environment(context, proxy.env(docker=True))
            proxy_metadata = {
                "proxy_trace": "enabled",
                "proxy_base_url": proxy.docker_base_url,
                "proxy_trace_path": str(proxy.config.trace_path),
            }
        try:
            completed = run_command(active_context.harness.command, active_context)
        finally:
            if proxy is not None:
                proxy.stop()
        result = result_from_completed(completed)
        native_events = parse_docker_agent_events(completed.stdout, active_context.harness.config)
        proxy_events = parse_proxy_trace_events(context.workspace, active_context.harness.config)
        parsed_events, selected_trace_source = _select_trace_events(native_events, proxy_events)
        if parsed_events:
            result.trace_events = parsed_events
        result.metadata.update(
            {
                "trace_quality": "structured" if any(event.type == "model_call" for event in parsed_events) else "partial",
                "bench_ready": bool(context.harness.config.get("bench_ready", True)),
                "version_check": version_check.to_metadata(),
            }
        )
        result.metadata.update(proxy_metadata)
        if proxy_events:
            result.metadata["proxy_trace"] = "parsed" if selected_trace_source == "proxy" else "available_not_selected"
        if selected_trace_source:
            result.metadata["selected_trace_source"] = selected_trace_source
        return result


def parse_docker_agent_events(stdout: str, config: dict[str, Any]) -> list[TraceEvent]:
    trace_config = _trace_config(config)
    parser = str(trace_config.get("parser", config.get("trace_parser", "generic_json")) or "none")
    if parser == "none":
        return []
    if parser == "aider_text":
        return _parse_aider_text_events(stdout)
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
                    cached_input_tokens=_cached_tokens(usage),
                    output_tokens=_int_value(usage.get("output_tokens", usage.get("completion_tokens", 0))),
                    reasoning_output_tokens=_reasoning_tokens(usage),
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
    proxy_config = trace_config.get("proxy") if isinstance(trace_config.get("proxy"), dict) else {}
    relative_path = (
        proxy_config.get("trace_path")
        or trace_config.get("proxy_trace_path")
        or trace_config.get("litellm_log_path")
        or config.get("litellm_log_path")
    )
    if not relative_path:
        return []
    trace_path = workspace / str(relative_path).lstrip("/")
    if not trace_path.exists():
        return []
    events: list[TraceEvent] = []
    call_index = 0
    default_source = "usage_proxy" if proxy_config.get("trace_path") or trace_config.get("proxy_trace_path") else "litellm_proxy"
    for raw in _parse_json_or_jsonl(trace_path.read_text(encoding="utf-8")):
        usage = _event_usage(raw)
        if not usage or not _usage_has_activity(usage):
            continue
        events.append(
            model_call_event(
                call_index=call_index,
                input_tokens=_input_tokens(usage),
                cached_input_tokens=_cached_tokens(usage),
                output_tokens=_int_value(usage.get("output_tokens", usage.get("completion_tokens", 0))),
                reasoning_output_tokens=_reasoning_tokens(usage),
                cost_usd=_cost_usd(raw, usage),
                metadata={"source": raw.get("source", default_source), "model": raw.get("model")},
            )
        )
        call_index += 1
    return events


def _with_proxy_environment(context: AdapterRunContext, proxy_env: dict[str, str]) -> AdapterRunContext:
    if not proxy_env:
        return context
    config = dict(context.harness.config)
    config["docker_add_host_gateway"] = True
    harness = replace(
        context.harness,
        env={**context.harness.env, **proxy_env},
        config=config,
    )
    return replace(context, harness=harness)


def _select_trace_events(native_events: list[TraceEvent], proxy_events: list[TraceEvent]) -> tuple[list[TraceEvent], str | None]:
    native_model_calls = [event for event in native_events if event.type == "model_call"]
    proxy_model_calls = [event for event in proxy_events if event.type == "model_call"]
    if proxy_model_calls and (
        len(proxy_model_calls) > len(native_model_calls)
        or (
            len(proxy_model_calls) == len(native_model_calls)
            and _calls_with_cost(proxy_model_calls) > _calls_with_cost(native_model_calls)
        )
    ):
        return [event for event in native_events if event.type != "model_call"] + proxy_events, "proxy"
    if native_model_calls:
        return native_events, "native"
    if proxy_model_calls:
        return native_events + proxy_events, "proxy"
    return native_events or proxy_events, None


def _calls_with_cost(events: list[TraceEvent]) -> int:
    return sum(1 for event in events if event.data.get("cost_usd") is not None)


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
    part = raw.get("part")
    if isinstance(part, dict) and isinstance(part.get("tokens"), dict):
        return _usage_from_token_block(part["tokens"])
    if any(key in raw for key in ("input_tokens", "prompt_tokens", "output_tokens", "completion_tokens")):
        return raw
    candidates: list[Any] = [
        raw.get("usage"),
        raw.get("token_usage"),
        raw.get("metrics", {}).get("usage") if isinstance(raw.get("metrics"), dict) else None,
        raw.get("message", {}).get("usage") if isinstance(raw.get("message"), dict) else None,
        raw.get("response", {}).get("usage") if isinstance(raw.get("response"), dict) else None,
        raw.get("metadata", {}).get("usage") if isinstance(raw.get("metadata"), dict) else None,
        raw.get("meta", {}).get("usage") if isinstance(raw.get("meta"), dict) else None,
        raw.get("meta", {}).get("tokenUsage") if isinstance(raw.get("meta"), dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return None


def _usage_has_activity(usage: dict[str, Any]) -> bool:
    return (
        _input_tokens(usage)
        + _int_value(usage.get("output_tokens", usage.get("completion_tokens", 0)))
        + _reasoning_tokens(usage)
    ) > 0


def _input_tokens(usage: dict[str, Any]) -> int:
    base_input = _int_value(usage.get("input_tokens", usage.get("prompt_tokens", 0)))
    if base_input:
        return base_input
    return _cached_tokens(usage) + _int_value(usage.get("cache_creation_input_tokens", 0))


def _cached_tokens(usage: dict[str, Any]) -> int:
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict):
        detail_value = _int_value(
            details.get("cached_tokens", details.get("cache_read_tokens", details.get("cache_read_input_tokens", 0)))
        )
        if detail_value:
            return detail_value
    details = usage.get("input_tokens_details")
    if isinstance(details, dict):
        detail_value = _int_value(
            details.get("cached_tokens", details.get("cache_read_tokens", details.get("cache_read_input_tokens", 0)))
        )
        if detail_value:
            return detail_value
    return _int_value(usage.get("cache_read_input_tokens", usage.get("cached_input_tokens", 0)))


def _reasoning_tokens(usage: dict[str, Any]) -> int:
    details = usage.get("completion_tokens_details")
    if isinstance(details, dict):
        detail_value = _int_value(details.get("reasoning_tokens"))
        if detail_value:
            return detail_value
    details = usage.get("output_tokens_details")
    if isinstance(details, dict):
        detail_value = _int_value(details.get("reasoning_tokens"))
        if detail_value:
            return detail_value
    return _int_value(usage.get("reasoning_output_tokens", usage.get("thinking_tokens", 0)))


def _tool_result(raw: dict[str, Any], parser: str) -> TraceEvent | None:
    role = raw.get("role")
    event_type = raw.get("type")
    if event_type == "tool_use" and isinstance(raw.get("part"), dict):
        part = raw["part"]
        state = part.get("state") if isinstance(part.get("state"), dict) else {}
        output = _content_text(state.get("output", state.get("metadata", {}).get("output") if isinstance(state.get("metadata"), dict) else ""))
        if not output:
            return None
        return tool_result_event(
            name=str(part.get("tool") or part.get("callID") or "tool"),
            output=output,
            metadata={"source": parser, "raw_event_type": event_type},
        )
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
    part = raw.get("part") if isinstance(raw.get("part"), dict) else {}
    candidates: list[Any] = [
        raw.get("cost_usd"),
        raw.get("total_cost_usd"),
        raw.get("response_cost"),
        raw.get("cost"),
        part.get("cost"),
        usage.get("cost_usd"),
        usage.get("cost"),
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


def _usage_from_token_block(tokens: dict[str, Any]) -> dict[str, Any]:
    cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
    return {
        "input_tokens": _int_value(tokens.get("input")),
        "cached_input_tokens": _int_value(cache.get("read")),
        "output_tokens": _int_value(tokens.get("output")),
        "reasoning_output_tokens": _int_value(tokens.get("reasoning")),
        "total_tokens": _int_value(tokens.get("total")),
    }


def _parse_aider_text_events(stdout: str) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    pattern = re.compile(
        r"Tokens:\s*(?P<input>[0-9][0-9,]*)\s+sent,\s*(?P<output>[0-9][0-9,]*)\s+received(?:\.\s*Cost:\s*\$?(?P<cost>[0-9.]+))?",
        re.IGNORECASE,
    )
    for call_index, match in enumerate(pattern.finditer(stdout)):
        events.append(
            model_call_event(
                call_index=call_index,
                input_tokens=_int_value(match.group("input").replace(",", "")),
                output_tokens=_int_value(match.group("output").replace(",", "")),
                cost_usd=_float_or_none(match.group("cost")),
                metadata={"source": "aider_text"},
            )
        )
    return events


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
