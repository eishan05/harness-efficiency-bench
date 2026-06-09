"""Markdown link normalization."""

import re


LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def normalize_links(markdown, base_url):
    def replace(match):
        label, target = match.groups()
        if "://" in target or target.startswith("#") or target.startswith("mailto:"):
            return match.group(0)
        return f"[{label}]({base_url.rstrip('/')}/{target.lstrip('./')})"

    return LINK_RE.sub(replace, markdown)
