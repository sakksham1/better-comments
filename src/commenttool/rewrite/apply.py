"""
Splices Rewrite results back into source bytes.

This is the structural enforcement point mentioned in the design doc: the
LLM never sees or returns "the new file" or "the new function" -- it only
returns replacement text for a comment span we already extracted via
tree-sitter. This function is the only place that mutates file content, and
it only ever replaces bytes in the range [comment.start_byte, comment.end_byte).

Multiple rewrites in the same file are applied in REVERSE byte-offset order
so earlier offsets stay valid as later (higher-offset) splices happen first.
"""
from __future__ import annotations

from ..models import Rewrite


def splice_rewrites(original: bytes, rewrites: list[Rewrite]) -> bytes:
    """Apply all rewrites for a single file's content, returning new bytes.

    Raises ValueError if any two rewrites have overlapping spans -- that
    should never happen (each Rewrite maps 1:1 to a distinct Comment
    extracted from this same file version), and if it does, something
    upstream is broken and we should fail loud rather than corrupt the file.
    """
    if not rewrites:
        return original

    ordered = sorted(rewrites, key=lambda r: r.comment.start_byte, reverse=True)

    _assert_no_overlaps(ordered)

    result = bytearray(original)
    for rewrite in ordered:
        c = rewrite.comment
        new_bytes = rewrite.new_text.encode("utf-8")
        result[c.start_byte:c.end_byte] = new_bytes

    return bytes(result)


def _assert_no_overlaps(ordered_desc: list[Rewrite]) -> None:
    for prev, cur in zip(ordered_desc, ordered_desc[1:]):
        if cur.comment.end_byte > prev.comment.start_byte:
            raise ValueError(
                f"overlapping comment spans in {prev.comment.file_path}: "
                f"[{cur.comment.start_byte},{cur.comment.end_byte}) and "
                f"[{prev.comment.start_byte},{prev.comment.end_byte})"
            )
