"""mini-swe-agent adapter."""

from __future__ import annotations

from .base import AdapterResult, AdapterRunContext, BaseAdapter
from .command import result_from_completed, run_command


class MiniSweAgentAdapter(BaseAdapter):
    name = "mini_swe_agent"

    def run(self, context: AdapterRunContext) -> AdapterResult:
        if not context.harness.command:
            return AdapterResult(
                exit_code=2,
                stderr=(
                    "mini_swe_agent adapter requires a command in the harness manifest "
                    "because mini-swe-agent installs vary by version.\n"
                ),
                metadata={"trace_quality": "none"},
            )
        completed = run_command(context.harness.command, context)
        result = result_from_completed(completed)
        result.metadata["trace_quality"] = "partial"
        return result

