"""
Generates unified diffs from (original bytes, rewritten bytes) pairs, so the
tool's default output is something reviewable via `git diff` / `git apply`,
never a silent in-place mutation.
"""
from __future__ import annotations

import difflib
from pathlib import Path


def make_file_diff(file_path: Path, original: bytes, rewritten: bytes) -> str:
    """Return a unified diff string for one file, git-apply compatible.

    Empty string if there's no change (callers should skip writing those).
    """
    if original == rewritten:
        return ""

    original_lines = original.decode("utf-8", errors="replace").splitlines(keepends=True)
    rewritten_lines = rewritten.decode("utf-8", errors="replace").splitlines(keepends=True)

    rel = str(file_path)
    diff_lines = difflib.unified_diff(
        original_lines,
        rewritten_lines,
        fromfile=f"a/{rel}",
        tofile=f"b/{rel}",
        lineterm="",
    )
    return "\n".join(diff_lines) + "\n"


def combine_diffs(diffs: list[str]) -> str:
    """Concatenate per-file diffs into a single patch file."""
    return "".join(d for d in diffs if d)
