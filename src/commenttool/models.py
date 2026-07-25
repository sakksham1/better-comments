"""
Core data structures shared across extraction, filtering, rewriting, and diffing.

Kept dependency-free (stdlib only) so every other module can import this
without pulling in tree-sitter / anthropic, which makes unit testing the
non-parsing logic (filters, diffing, cache) trivial.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class CommentStyle(str, Enum):
    LINE = "line"    # //, #, --
    BLOCK = "block"  # /* */, """ """, etc.


class AttachmentKind(str, Enum):
    LEADING = "leading"      # sits on its own line(s) directly above a node
    TRAILING = "trailing"    # shares a line with the end of a code statement
    INTERNAL = "internal"    # inside a block body, not clearly bound to one line
    DANGLING = "dangling"    # no discernible attachment (EOF, blank surroundings)


@dataclass(frozen=True)
class CodeContext:
    """The code a comment is attached to, for LLM context and for scoring."""
    node_type: str       # tree-sitter node type, e.g. "function_definition"
    node_text: str        # source text of the attached node (may be truncated by caller)
    start_line: int
    end_line: int


@dataclass
class Comment:
    """A single comment extracted from a source file."""
    file_path: Path
    language: str
    text: str                          # raw comment text, delimiters included
    start_byte: int
    end_byte: int
    start_line: int
    end_line: int
    style: CommentStyle
    attachment: AttachmentKind
    context: Optional[CodeContext] = None

    @property
    def id(self) -> str:
        """Stable-ish identifier for caching / reporting within a single file version."""
        return f"{self.file_path}:{self.start_byte}-{self.end_byte}"


@dataclass
class FlagResult:
    """Output of the filter stage: a comment plus why it was (or wasn't) flagged."""
    comment: Comment
    score: float                        # 0.0-1.0, higher = more likely AI-slop/redundant
    reasons: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return self.score > 0  # thresholding happens at the caller (CLI --confidence)


@dataclass
class Rewrite:
    """Output of the rewrite stage: what to replace a flagged comment's text with."""
    comment: Comment
    new_text: str
    reason: str = ""

    @property
    def is_noop(self) -> bool:
        return self.new_text.strip() == self.comment.text.strip()


@dataclass
class FileResult:
    """Aggregated results for one file, used by both `scan` and `apply`."""
    file_path: Path
    file_hash: str
    flags: list[FlagResult] = field(default_factory=list)
    rewrites: list[Rewrite] = field(default_factory=list)
