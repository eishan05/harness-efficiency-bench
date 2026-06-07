"""Qwen Code adapter."""

from __future__ import annotations

from .base import AdapterResult, AdapterRunContext, BaseAdapter
from .command import result_from_completed, run_command


class QwenCodeAdapter(BaseAdapter):
    name = "qwen_code"

    def run(self, context: AdapterRunContext) -> AdapterResult:
        command = context.harness.command or ["qwen", "-p", "{prompt}"]
        completed = run_command(command, context)
        result = result_from_completed(completed)
        result.metadata["trace_quality"] = "partial"
        return result

