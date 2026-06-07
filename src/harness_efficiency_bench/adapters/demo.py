"""Deterministic demo adapter used for tests and smoke runs."""

from __future__ import annotations

from .base import AdapterResult, AdapterRunContext, BaseAdapter
from ..tokenization import count_tokens
from ..tracing import model_call_event, tool_result_event


class DemoAdapter(BaseAdapter):
    name = "demo"

    def run(self, context: AdapterRunContext) -> AdapterResult:
        oracle = context.task.oracle
        if oracle.type in {"file_equals", "file_contains"} and oracle.path:
            target = context.workspace / oracle.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(oracle.text or "", encoding="utf-8")

        injected_prefix = "You are a benchmark demo harness. Follow the task exactly."
        first_input = f"{injected_prefix}\n\n{context.prompt}"
        tool_output = "workspace listing: answer.txt"
        second_input = f"{first_input}\n\nPrevious tool output:\n{tool_output}\n\nReady to finalize."
        events = [
            model_call_event(
                call_index=0,
                input_text=first_input,
                input_tokens=count_tokens(first_input),
                output_tokens=12,
                cost_usd=0.0,
            ),
            tool_result_event(name="list_workspace", output=tool_output, call_index=0),
            model_call_event(
                call_index=1,
                input_text=second_input,
                input_tokens=count_tokens(second_input),
                output_tokens=8,
                cost_usd=0.0,
            ),
        ]
        return AdapterResult(
            exit_code=0,
            stdout="demo adapter completed\n",
            trace_events=events,
            metadata={"trace_quality": "full", "synthetic": True},
        )

