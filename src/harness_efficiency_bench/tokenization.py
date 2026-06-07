"""Token counting helpers.

The benchmark prefers provider-reported token counts. This module is the fallback
for local prompts, tool outputs, and synthetic traces.
"""

from __future__ import annotations

import re


_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def count_tokens(text: str | None) -> int:
    """Return a deterministic approximate token count for local text."""

    if not text:
        return 0
    return len(_TOKEN_RE.findall(text))


def make_token_payload(target_tokens: int, seed: str = "irrelevant context") -> str:
    """Create deterministic context bloat with approximately target_tokens tokens."""

    if target_tokens <= 0:
        return ""
    base = _TOKEN_RE.findall(seed) or ["context"]
    words = [base[i % len(base)] for i in range(target_tokens)]
    return " ".join(words)

