"""Claude Code adapter."""

from __future__ import annotations

import json
import os
import re
from dataclasses import replace
from typing import Any

from .base import AdapterResult, AdapterRunContext, BaseAdapter
from .command import missing_required_env, parse_jsonl_events, result_from_completed, run_command
from .docker_agent_cli import _select_trace_events, parse_proxy_trace_events
from ..tracing import TraceEvent, model_call_event, tool_result_event
from ..usage_proxy import proxy_from_config


class ClaudeCodeAdapter(BaseAdapter):
    name = "claude_code"

    def run(self, context: AdapterRunContext) -> AdapterResult:
        missing = missing_required_env(context)
        if missing:
            return AdapterResult(
                exit_code=2,
                stderr=f"missing required environment variables: {', '.join(missing)}\n",
                metadata={"trace_quality": "none", "missing_required_env": missing},
            )
        active_context = _with_openrouter_environment(context)
        proxy = proxy_from_config(active_context.workspace, active_context.harness.config)
        proxy_metadata: dict[str, Any] = {}
        if proxy is not None:
            proxy.start()
            active_context = _with_proxy_environment(
                active_context,
                proxy.env(docker=_is_docker_backend(active_context)),
            )
            proxy_metadata = {
                "proxy_trace": "enabled",
                "proxy_base_url": proxy.docker_base_url if _is_docker_backend(active_context) else proxy.local_base_url,
                "proxy_trace_path": str(proxy.config.trace_path),
            }
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
        try:
            completed = run_command(command, active_context)
        finally:
            if proxy is not None:
                proxy.stop()
        result = result_from_completed(completed)
        native_events = self._parse_events(completed.stdout)
        proxy_events = parse_proxy_trace_events(context.workspace, active_context.harness.config)
        if proxy_events:
            proxy_events = _mark_preflight_proxy_calls(proxy_events, native_events)
        parsed_events, selected_trace_source = _select_trace_events(native_events, proxy_events)
        result.trace_events = parsed_events
        result.metadata["trace_quality"] = "structured" if any(event.type == "model_call" for event in parsed_events) else "partial"
        result.metadata["model_id"] = active_context.harness.model
        result.metadata["bench_ready"] = bool(context.harness.config.get("bench_ready", True))
        result.metadata.update(proxy_metadata)
        if proxy is not None:
            result.metadata["proxy_trace"] = "parsed" if proxy_events and selected_trace_source == "proxy" else "available_not_selected" if proxy_events else "enabled_no_usage"
        if selected_trace_source:
            result.metadata["selected_trace_source"] = selected_trace_source
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
                        reasoning_output_tokens=_reasoning_tokens(usage),
                        cost_usd=_cost_usd(raw, usage),
                        metadata=_usage_metadata(usage, "claude_stream_json", event_type),
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


def _with_openrouter_environment(context: AdapterRunContext) -> AdapterRunContext:
    if context.harness.config.get("auth_mode") != "openrouter":
        return context
    source_env = {**os.environ, **context.harness.env}
    api_key = source_env.get("OPENROUTER_API_KEY", "")
    model = _expand_env_vars(context.harness.model or source_env.get("OPENROUTER_MODEL", ""), source_env)
    base_url = str(context.harness.config.get("openrouter_base_url") or "https://openrouter.ai/api")
    env = {
        **context.harness.env,
        "ANTHROPIC_BASE_URL": base_url,
        "ANTHROPIC_AUTH_TOKEN": api_key,
        "ANTHROPIC_API_KEY": "",
    }
    if model:
        env.setdefault("ANTHROPIC_MODEL", model)
        env.setdefault("ANTHROPIC_DEFAULT_OPUS_MODEL", model)
        env.setdefault("ANTHROPIC_DEFAULT_SONNET_MODEL", model)
        env.setdefault("ANTHROPIC_DEFAULT_HAIKU_MODEL", model)
        env.setdefault("CLAUDE_CODE_SUBAGENT_MODEL", model)
    harness = replace(context.harness, env=env, model=model or context.harness.model)
    return replace(context, harness=harness)


def _with_proxy_environment(context: AdapterRunContext, proxy_env: dict[str, str]) -> AdapterRunContext:
    if not proxy_env:
        return context
    config = dict(context.harness.config)
    if _is_docker_backend(context):
        config["docker_add_host_gateway"] = True
    harness = replace(
        context.harness,
        env={**context.harness.env, **proxy_env},
        config=config,
    )
    return replace(context, harness=harness)


def _is_docker_backend(context: AdapterRunContext) -> bool:
    return context.harness.config.get("backend") == "docker"


def _mark_preflight_proxy_calls(proxy_events: list[TraceEvent], native_events: list[TraceEvent]) -> list[TraceEvent]:
    visible_request_ids = _visible_assistant_message_ids(native_events)
    if not visible_request_ids:
        return proxy_events
    marked: list[TraceEvent] = []
    for event in proxy_events:
        if event.type != "model_call":
            marked.append(event)
            continue
        metadata = dict(event.data.get("metadata", {})) if isinstance(event.data.get("metadata"), dict) else {}
        request_id = metadata.get("request_id")
        if request_id and str(request_id) not in visible_request_ids:
            data = dict(event.data)
            metadata["preflight"] = True
            metadata["preflight_reason"] = "proxy request_id not present in Claude assistant stream"
            data["metadata"] = metadata
            marked.append(TraceEvent(type=event.type, timestamp=event.timestamp, data=data))
        else:
            marked.append(event)
    return marked


def _visible_assistant_message_ids(events: list[TraceEvent]) -> set[str]:
    message_ids: set[str] = set()
    for event in events:
        if event.type != "claude_event":
            continue
        raw = event.data.get("raw")
        if not isinstance(raw, dict) or raw.get("type") != "assistant":
            continue
        message = raw.get("message")
        message_id = message.get("id") if isinstance(message, dict) else None
        if isinstance(message_id, str) and message_id:
            message_ids.add(message_id)
    return message_ids


def _expand_env_vars(value: str | None, env: dict[str, str]) -> str:
    if not value:
        return ""

    def replace_match(match: re.Match[str]) -> str:
        key = match.group("braced") or match.group("plain") or ""
        return str(env.get(key, match.group(0)))

    return re.sub(r"\$\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|\$(?P<plain>[A-Za-z_][A-Za-z0-9_]*)", replace_match, value)


def _event_usage(raw: dict[str, Any]) -> dict[str, Any] | None:
    model_usage = _model_usage(raw.get("modelUsage"))
    if isinstance(model_usage, dict) and _usage_has_activity(model_usage):
        return model_usage
    usage = raw.get("usage")
    if isinstance(usage, dict) and _usage_has_activity(usage):
        return usage
    message = raw.get("message")
    message_usage = message.get("usage") if isinstance(message, dict) else None
    if isinstance(message_usage, dict) and _usage_has_activity(message_usage):
        return message_usage
    if isinstance(usage, dict):
        return usage
    if isinstance(message_usage, dict):
        return message_usage
    return model_usage


def _apply_result_usage(
    normalized: list[TraceEvent],
    model_call_positions: list[int],
    result_event: dict[str, Any],
    next_call_index: int,
) -> None:
    total_cost = _cost_usd(result_event)
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
            reasoning_output_tokens=_reasoning_tokens(usage),
            cost_usd=_cost_usd(result_event, usage),
            metadata={
                **_usage_metadata(usage, "claude_result_usage", result_event.get("type")),
                "cost_source": "claude_result_total",
            },
        )
    )


def _usage_has_activity(usage: dict[str, Any]) -> bool:
    return (
        _input_tokens(usage)
        + _int_value(usage.get("output_tokens", usage.get("completion_tokens", 0)))
        + _reasoning_tokens(usage)
    ) > 0


def _input_tokens(usage: dict[str, Any]) -> int:
    base_input = _int_value(usage.get("input_tokens", usage.get("prompt_tokens", usage.get("inputTokens", 0))))
    cache_read = _int_value(
        usage.get(
            "cache_read_input_tokens",
            usage.get("cached_input_tokens", usage.get("cacheReadInputTokens", 0)),
        )
    )
    cache_creation = _cache_creation_tokens(usage)
    return base_input + cache_read + cache_creation


def _cache_creation_tokens(usage: dict[str, Any]) -> int:
    explicit = _int_value(usage.get("cache_creation_input_tokens", usage.get("cacheCreationInputTokens", 0)))
    if explicit:
        return explicit
    details = usage.get("cache_creation")
    if isinstance(details, dict):
        return sum(_int_value(value) for value in details.values())
    return 0


def _reasoning_tokens(usage: dict[str, Any]) -> int:
    return _int_value(
        usage.get(
            "reasoning_output_tokens",
            usage.get("reasoning_tokens", usage.get("reasoningTokens", usage.get("thinking_tokens", 0))),
        )
    )


def _model_usage(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    entries: list[tuple[str | None, dict[str, Any]]] = []
    if any(key in value for key in ("inputTokens", "input_tokens", "outputTokens", "output_tokens")):
        entries.append((None, value))
    else:
        entries.extend(
            (str(model_id), usage)
            for model_id, usage in value.items()
            if isinstance(usage, dict)
        )
    if not entries:
        return None
    usage = {
        "input_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "cost_usd": 0.0,
        "_source": "claude_openrouter_model_usage",
        "_models": [],
    }
    cost_available = False
    for model_id, item in entries:
        usage["input_tokens"] += _int_value(item.get("inputTokens", item.get("input_tokens", item.get("prompt_tokens", 0))))
        usage["cache_read_input_tokens"] += _int_value(
            item.get("cacheReadInputTokens", item.get("cache_read_input_tokens", item.get("cached_input_tokens", 0)))
        )
        usage["cache_creation_input_tokens"] += _int_value(
            item.get("cacheCreationInputTokens", item.get("cache_creation_input_tokens", 0))
        )
        usage["output_tokens"] += _int_value(item.get("outputTokens", item.get("output_tokens", item.get("completion_tokens", 0))))
        usage["reasoning_output_tokens"] += _int_value(
            item.get(
                "reasoningOutputTokens",
                item.get("reasoningTokens", item.get("reasoning_output_tokens", item.get("thinking_tokens", 0))),
            )
        )
        cost = _float_or_none(item.get("costUSD", item.get("cost_usd", item.get("total_cost_usd"))))
        if cost is not None:
            usage["cost_usd"] += cost
            cost_available = True
        if model_id:
            usage["_models"].append(model_id)
    if not cost_available:
        usage.pop("cost_usd", None)
    return usage


def _usage_metadata(usage: dict[str, Any], default_source: str, event_type: Any) -> dict[str, Any]:
    metadata = {
        "source": str(usage.get("_source") or default_source),
        "raw_event_type": event_type,
    }
    models = usage.get("_models")
    if isinstance(models, list) and models:
        metadata["models"] = [str(model) for model in models]
        metadata["aggregate"] = True
    return metadata


def _cost_usd(raw: dict[str, Any], usage: dict[str, Any] | None = None) -> float | None:
    candidates: list[Any] = [raw.get("total_cost_usd"), raw.get("cost_usd")]
    if isinstance(usage, dict):
        candidates.extend([usage.get("cost_usd"), usage.get("costUSD"), usage.get("total_cost_usd")])
    for candidate in candidates:
        value = _float_or_none(candidate)
        if value is not None:
            return value
    return None


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
