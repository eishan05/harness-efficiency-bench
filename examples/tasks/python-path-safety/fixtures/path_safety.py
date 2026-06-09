"""Path safety helpers."""

from pathlib import Path


def safe_join(root, member):
    candidate = Path(root) / member
    if ".." in Path(member).parts:
        raise ValueError(f"unsafe member path: {member}")
    return candidate
