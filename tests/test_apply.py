from pathlib import Path

import pytest

from commenttool.models import AttachmentKind, Comment, CommentStyle, Rewrite
from commenttool.rewrite.apply import splice_rewrites


def _comment(start, end, text) -> Comment:
    return Comment(
        file_path=Path("sample.py"),
        language="python",
        text=text,
        start_byte=start,
        end_byte=end,
        start_line=1,
        end_line=1,
        style=CommentStyle.LINE,
        attachment=AttachmentKind.LEADING,
    )


def test_single_splice():
    original = b"x = 1  # old comment\ny = 2"
    span_start = original.index(b"#")
    span_end = len(b"x = 1  # old comment")
    c = _comment(span_start, span_end, "# old comment")
    rw = Rewrite(comment=c, new_text="# new comment")
    result = splice_rewrites(original, [rw])
    assert result == b"x = 1  # new comment\ny = 2"


def test_multiple_splices_reverse_order_safe():
    original = b"# first\nx = 1\n# second\ny = 2"
    c1 = _comment(0, 7, "# first")
    c2 = _comment(15, 22, "# second")
    rewrites = [
        Rewrite(comment=c1, new_text="# FIRST"),
        Rewrite(comment=c2, new_text="# SECOND"),
    ]
    result = splice_rewrites(original, rewrites)
    assert b"# FIRST" in result and b"# SECOND" in result
    assert b"x = 1" in result and b"y = 2" in result


def test_overlapping_spans_raise():
    original = b"# comment"
    c1 = _comment(0, 9, "# comment")
    c2 = _comment(3, 9, "mment")
    rewrites = [Rewrite(comment=c1, new_text="a"), Rewrite(comment=c2, new_text="b")]
    with pytest.raises(ValueError):
        splice_rewrites(original, rewrites)
