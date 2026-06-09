"""Build task cards from specs."""

from pathlib import Path


def _parse_spec(path):
    data = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def build_task_card(spec_dir):
    spec = _parse_spec(Path(spec_dir) / "deprecated.md")
    return f"{spec.get('title', 'Untitled')} - {spec.get('owner', 'unknown')} ({spec.get('priority', 'normal')})"
