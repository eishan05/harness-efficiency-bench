"""Generic command-line adapter."""

from __future__ import annotations

from .base import AdapterResult, AdapterRunContext, BaseAdapter
from .command import result_from_completed, run_command


class GenericCliAdapter(BaseAdapter):
    name = "generic_cli"

    def run(self, context: AdapterRunContext) -> AdapterResult:
        if not context.harness.command:
            return AdapterResult(
                exit_code=2,
                stderr="generic_cli adapter requires a command in the harness manifest\n",
                metadata={"trace_quality": "none"},
            )
        completed = run_command(context.harness.command, context)
        result = result_from_completed(completed)
        result.metadata["trace_quality"] = "partial"
        return result

