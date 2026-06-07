"""Codex adapter."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from .base import AdapterResult, AdapterRunContext, BaseAdapter
from .command import parse_jsonl_events, result_from_completed, run_command
from ..tracing import TraceEvent, model_call_event, tool_result_event


class CodexAdapter(BaseAdapter):
    name = "codex"

    def run(self, context: AdapterRunContext) -> AdapterResult:
        command = context.harness.command or [
            "codex",
            "exec",
            "--json",
            "--sandbox",
            "workspace-write",
            "--skip-git-repo-check",
            "-",
        ]
        trace_root = self._trace_root(context)
        run_context = self._context_with_rollout_trace(context, trace_root)
        completed = run_command(command, run_context, stdin=context.prompt)
        result = result_from_completed(completed)
        rollout_events = []
        if trace_root:
            rollout_events = self._parse_rollout_trace_events(trace_root)
            if not context.harness.config.get("retain_codex_rollout_trace"):
                shutil.rmtree(trace_root, ignore_errors=True)
        result.trace_events = self._parse_events(
            completed.stdout,
            include_turn_completed_usage=not rollout_events,
        ) + rollout_events
        result.metadata["trace_quality"] = "structured"
        if rollout_events:
            result.metadata["codex_rollout_trace"] = "parsed"
        elif trace_root:
            result.metadata["codex_rollout_trace"] = "enabled_no_model_usage"
        return result

    @staticmethod
    def _parse_events(stdout: str, *, include_turn_completed_usage: bool = True) -> list[TraceEvent]:
        normalized: list[TraceEvent] = []
        call_index = 0
        for raw in parse_jsonl_events(stdout):
            event_type = raw.get("type")
            if (
                include_turn_completed_usage
                and event_type == "turn.completed"
                and isinstance(raw.get("usage"), dict)
            ):
                usage: dict[str, Any] = raw["usage"]
                input_tokens = int(usage.get("input_tokens", 0) or 0)
                cached = int(usage.get("cached_input_tokens", 0) or 0)
                output_tokens = int(usage.get("output_tokens", 0) or 0)
                reasoning = int(usage.get("reasoning_output_tokens", 0) or 0)
                normalized.append(
                    model_call_event(
                        call_index=call_index,
                        input_tokens=input_tokens,
                        cached_input_tokens=cached,
                        output_tokens=output_tokens,
                        reasoning_output_tokens=reasoning,
                        metadata={"source": "codex_json", "raw_event_type": event_type},
                    )
                )
                call_index += 1
            elif event_type:
                item = raw.get("item")
                if isinstance(item, dict) and item.get("type") == "command_execution" and item.get("aggregated_output"):
                    normalized.append(
                        tool_result_event(
                            name=str(item.get("command", "command_execution")),
                            output=str(item.get("aggregated_output", "")),
                            metadata={
                                "source": "codex_json",
                                "status": item.get("status"),
                                "exit_code": item.get("exit_code"),
                            },
                        )
                    )
                normalized.append(TraceEvent(type="codex_event", data={"raw": raw}))
        return normalized

    @staticmethod
    def _rollout_model_calls_from_state(state: dict[str, Any]) -> list[TraceEvent]:
        inference_calls = state.get("inference_calls")
        if not isinstance(inference_calls, dict):
            return []
        ordered = sorted(
            (item for item in inference_calls.values() if isinstance(item, dict)),
            key=lambda item: int(item.get("execution", {}).get("started_seq", 0) or 0),
        )
        events: list[TraceEvent] = []
        for call_index, item in enumerate(ordered):
            usage = item.get("usage")
            if not isinstance(usage, dict):
                continue
            events.append(
                model_call_event(
                    call_index=call_index,
                    input_tokens=int(usage.get("input_tokens", 0) or 0),
                    cached_input_tokens=int(usage.get("cached_input_tokens", 0) or 0),
                    output_tokens=int(usage.get("output_tokens", 0) or 0),
                    reasoning_output_tokens=int(usage.get("reasoning_output_tokens", 0) or 0),
                    metadata={
                        "source": "codex_rollout_trace",
                        "inference_call_id": item.get("inference_call_id"),
                        "codex_turn_id": item.get("codex_turn_id"),
                        "model": item.get("model"),
                        "provider_name": item.get("provider_name"),
                    },
                )
            )
        return events

    def _parse_rollout_trace_events(self, trace_root: Path) -> list[TraceEvent]:
        for attempt in range(20):
            events = self._parse_rollout_trace_events_once(trace_root)
            if events or attempt == 19:
                return events
            time.sleep(0.1)
        return []

    def _parse_rollout_trace_events_once(self, trace_root: Path) -> list[TraceEvent]:
        events: list[TraceEvent] = []
        if not trace_root.exists():
            return events
        for bundle in sorted(trace_root.iterdir()):
            if not bundle.is_dir() or not (bundle / "manifest.json").exists():
                continue
            events.extend(self._rollout_model_calls_from_bundle(bundle))
        return events

    @staticmethod
    def _rollout_model_calls_from_bundle(bundle: Path) -> list[TraceEvent]:
        trace_path = bundle / "trace.jsonl"
        if not trace_path.exists():
            return []
        starts: dict[str, dict[str, Any]] = {}
        completed: list[dict[str, Any]] = []
        try:
            lines = trace_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines:
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = raw.get("payload")
            if not isinstance(payload, dict):
                continue
            event_type = payload.get("type")
            inference_call_id = payload.get("inference_call_id")
            if not inference_call_id:
                continue
            if event_type == "inference_started":
                starts[str(inference_call_id)] = {
                    "inference_call_id": str(inference_call_id),
                    "codex_turn_id": payload.get("codex_turn_id"),
                    "execution": {"started_seq": raw.get("seq", 0)},
                    "model": payload.get("model"),
                    "provider_name": payload.get("provider_name"),
                }
            elif event_type == "inference_completed":
                response_ref = payload.get("response_payload")
                usage = _usage_from_response_payload(bundle, response_ref)
                item = dict(starts.get(str(inference_call_id), {}))
                item.setdefault("inference_call_id", str(inference_call_id))
                item.setdefault("execution", {"started_seq": raw.get("seq", 0)})
                if usage:
                    item["usage"] = usage
                completed.append(item)
        return CodexAdapter._rollout_model_calls_from_state(
            {"inference_calls": {item["inference_call_id"]: item for item in completed}}
        )

    def _trace_root(self, context: AdapterRunContext) -> Path | None:
        if not context.harness.config.get("codex_rollout_trace"):
            return None
        trace_root = (context.workspace / ".codex_rollout_trace").resolve()
        trace_root.mkdir(parents=True, exist_ok=True)
        return trace_root

    def _context_with_rollout_trace(
        self,
        context: AdapterRunContext,
        trace_root: Path | None,
    ) -> AdapterRunContext:
        if trace_root is None:
            return context
        env_trace_root = str(trace_root)
        if context.harness.config.get("backend") == "docker":
            docker_workspace = str(context.harness.config.get("docker_workspace", "/workspace"))
            env_trace_root = f"{docker_workspace}/.codex_rollout_trace"
        harness = replace(
            context.harness,
            env={**context.harness.env, "CODEX_ROLLOUT_TRACE_ROOT": env_trace_root},
        )
        return replace(context, harness=harness)


def _usage_from_response_payload(bundle: Path, response_ref: Any) -> dict[str, Any] | None:
    if not isinstance(response_ref, dict):
        return None
    relative_path = response_ref.get("path")
    if not relative_path:
        return None
    response_path = bundle / str(relative_path)
    try:
        response = json.loads(response_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    usage = response.get("token_usage") or response.get("usage")
    return usage if isinstance(usage, dict) else None
