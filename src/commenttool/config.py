"""
Tool-wide config. v0 keeps this to CLI flags + a few constants; promote to
a `.commenttool.toml` file once there are enough knobs that repeated flags
get annoying (per-directory excludes, org-wide style guide text, etc.).
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_EXCLUDES = (
    ".git",
    "node_modules",
    "vendor",
    "dist",
    "build",
    ".venv",
    "venv",
    "__pycache__",
    ".commenttool_cache.json",
)


@dataclass
class ScanConfig:
    confidence: float = 0.4       # min FlagResult.score to be considered "flagged"
    excludes: tuple[str, ...] = field(default_factory=lambda: DEFAULT_EXCLUDES)
    use_cache: bool = True
    max_file_size_bytes: int = 2_000_000  # skip huge generated/vendored files
