"""
Simple file-hash cache so repeat `scan` runs don't re-parse and re-score
unchanged files. Deliberately dumb (single JSON file) for v0 — swap for
sqlite if the JSON gets unwieldy on huge repos.

Cache is keyed by (relative file path -> content hash -> last scan summary).
We store the hash rather than mtime because mtime is unreliable across
git checkouts/CI and hash correctness matters more than a few wasted ms.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

CACHE_FILENAME = ".commenttool_cache.json"


def hash_content(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class ScanCache:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.path = repo_root / CACHE_FILENAME
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def save(self) -> None:
        self.path.write_text(json.dumps(self._data, indent=2, sort_keys=True))

    def is_unchanged(self, rel_path: str, content_hash: str) -> bool:
        entry = self._data.get(rel_path)
        return entry is not None and entry.get("hash") == content_hash

    def get_cached_flag_count(self, rel_path: str) -> int:
        entry = self._data.get(rel_path)
        return entry.get("flag_count", 0) if entry else 0

    def update(self, rel_path: str, content_hash: str, flag_count: int) -> None:
        self._data[rel_path] = {"hash": content_hash, "flag_count": flag_count}

    def invalidate(self, rel_path: str) -> None:
        self._data.pop(rel_path, None)
