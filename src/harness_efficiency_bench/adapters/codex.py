"""Codex adapter."""

from __future__ import annotations

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
        completed = run_command(command, context, stdin=context.prompt)
        result = result_from_completed(completed)
        result.trace_events = self._parse_events(completed.stdout)
        result.metadata["trace_quality"] = "structured"
        return result

    @staticmethod
    def _parse_events(stdout: str) -> list[TraceEvent]:
        normalized: list[TraceEvent] = []
        call_index = 0
        for raw in parse_jsonl_events(stdout):
            event_type = raw.get("type")
            if event_type == "turn.completed" and isinstance(raw.get("usage"), dict):
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
