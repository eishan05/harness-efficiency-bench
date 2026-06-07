"""Google Antigravity adapter."""

from __future__ import annotations

import asyncio
from typing import Any

from .base import AdapterResult, AdapterRunContext, BaseAdapter
from .command import result_from_completed, run_command
from ..tracing import TraceEvent, model_call_event


class AntigravityAdapter(BaseAdapter):
    name = "antigravity"

    def run(self, context: AdapterRunContext) -> AdapterResult:
        mode = str(context.harness.config.get("mode", "sdk"))
        if mode == "cli":
            command = context.harness.command or ["agy", "-p", "{prompt}", "--cwd", "{workspace}"]
            completed = run_command(command, context)
            result = result_from_completed(completed)
            result.metadata["trace_quality"] = "partial"
            return result
        return asyncio.run(self._run_sdk(context))

    async def _run_sdk(self, context: AdapterRunContext) -> AdapterResult:
        try:
            from google.antigravity import Agent, LocalAgentConfig  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on optional SDK
            return AdapterResult(
                exit_code=2,
                stderr=(
                    "antigravity SDK mode requires the google-antigravity package. "
                    "Set config.mode=cli to use agy -p instead.\n"
                    f"{exc}\n"
                ),
                metadata={"trace_quality": "none"},
            )

        config_kwargs: dict[str, Any] = dict(context.harness.config.get("sdk_config", {}))
        config_kwargs.setdefault("cwd", str(context.workspace))
        response_text = ""
        events: list[TraceEvent] = []
        async with Agent(LocalAgentConfig(**config_kwargs)) as agent:
            response = await agent.chat(context.prompt)
            if hasattr(response, "text"):
                response_text = await response.text()
            usage = getattr(response, "usage_metadata", None)
            usage_dict = _usage_to_dict(usage)
            if usage_dict:
                events.append(
                    model_call_event(
                        call_index=0,
                        input_tokens=int(usage_dict.get("prompt_tokens", 0) or 0),
                        cached_input_tokens=int(usage_dict.get("cached_tokens", 0) or 0),
                        output_tokens=int(usage_dict.get("candidate_tokens", 0) or 0),
                        reasoning_output_tokens=int(usage_dict.get("thinking_tokens", 0) or 0),
                        metadata={"source": "antigravity_sdk"},
                    )
                )
        return AdapterResult(
            exit_code=0,
            stdout=response_text,
            trace_events=events,
            metadata={"trace_quality": "structured"},
        )


def _usage_to_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return usage
    if hasattr(usage, "model_dump"):
        return dict(usage.model_dump())
    if hasattr(usage, "__dict__"):
        return dict(usage.__dict__)
    return {}

