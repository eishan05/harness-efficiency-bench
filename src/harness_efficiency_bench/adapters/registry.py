"""Adapter registry."""

from __future__ import annotations

from ..manifests import HarnessManifest
from .antigravity import AntigravityAdapter
from .base import BaseAdapter
from .claude_code import ClaudeCodeAdapter
from .codex import CodexAdapter
from .demo import DemoAdapter
from .docker_agent_cli import DockerAgentCliAdapter
from .generic_cli import GenericCliAdapter
from .mini_swe_agent import MiniSweAgentAdapter
from .nanobot import NanobotAdapter
from .qwen_code import QwenCodeAdapter


_ADAPTERS: dict[str, type[BaseAdapter]] = {
    "antigravity": AntigravityAdapter,
    "claude_code": ClaudeCodeAdapter,
    "codex": CodexAdapter,
    "demo": DemoAdapter,
    "docker_agent_cli": DockerAgentCliAdapter,
    "generic_cli": GenericCliAdapter,
    "mini_swe_agent": MiniSweAgentAdapter,
    "nanobot": NanobotAdapter,
    "qwen_code": QwenCodeAdapter,
}


def create_adapter(manifest: HarnessManifest) -> BaseAdapter:
    try:
        adapter_cls = _ADAPTERS[manifest.adapter]
    except KeyError as exc:
        known = ", ".join(sorted(_ADAPTERS))
        raise ValueError(f"unknown adapter {manifest.adapter!r}; known adapters: {known}") from exc
    return adapter_cls(manifest)
