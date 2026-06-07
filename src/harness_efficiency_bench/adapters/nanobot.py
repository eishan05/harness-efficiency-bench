"""nanobot adapter."""

from __future__ import annotations

from .base import AdapterResult, AdapterRunContext, BaseAdapter
from .command import result_from_completed, run_command


class NanobotAdapter(BaseAdapter):
    name = "nanobot"

    def run(self, context: AdapterRunContext) -> AdapterResult:
        if not context.harness.command:
            return AdapterResult(
                exit_code=2,
                stderr=(
                    "nanobot adapter requires a command in the harness manifest. "
                    "Use the command field to point at your configured nanobot CLI, gateway, or script.\n"
                ),
                metadata={"trace_quality": "none"},
            )
        completed = run_command(context.harness.command, context)
        result = result_from_completed(completed)
        result.metadata["trace_quality"] = "partial"
        return result

