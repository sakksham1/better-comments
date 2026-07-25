"""Walks a directory tree yielding supported source files, respecting excludes."""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .config import ScanConfig
from .languages import is_supported


def iter_source_files(root: Path, config: ScanConfig) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if not is_supported(path):
            continue
        if _is_excluded(path, root, config.excludes):
            continue
        try:
            if path.stat().st_size > config.max_file_size_bytes:
                continue
        except OSError:
            continue
        yield path


def _is_excluded(path: Path, root: Path, excludes: tuple[str, ...]) -> bool:
    rel_parts = path.relative_to(root).parts
    return any(part in excludes for part in rel_parts)
