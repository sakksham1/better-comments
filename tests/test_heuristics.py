from pathlib import Path

from commenttool.filters.heuristics import score_comment, should_skip
from commenttool.models import AttachmentKind, CodeContext, Comment, CommentStyle


def _make_comment(text: str, code: str = "x = 1") -> Comment:
    return Comment(
        file_path=Path("sample.py"),
        language="python",
        text=text,
        start_byte=0,
        end_byte=len(text),
        start_line=1,
        end_line=1,
        style=CommentStyle.LINE,
        attachment=AttachmentKind.LEADING,
        context=CodeContext(node_type="expression_statement", node_text=code, start_line=2, end_line=2),
    )


def test_license_header_skipped():
    c = _make_comment("# Copyright 2024 Example Corp, licensed under MIT")
    assert should_skip(c) is not None


def test_todo_skipped():
    c = _make_comment("# TODO: revisit this later")
    assert should_skip(c) is not None


def test_redundant_comment_flagged():
    # High identifier overlap with the code it's attached to -> should score high.
    # Note: this heuristic catches restatement via shared identifiers, not pure
    # paraphrase ("loop through users" over "for user in users" has almost no
    # token overlap despite being just as redundant) -- that gap is exactly
    # what the LLM classification step is for; this layer only needs to be
    # cheap and over-inclusive, not perfect.
    c = _make_comment("# set user active", code="user.active = True")
    result = score_comment(c)
    assert result.score > 0.3


def test_ai_tell_phrase_flagged():
    c = _make_comment("# This function is responsible for validating input")
    result = score_comment(c)
    assert any("AI-tell" in r for r in result.reasons)


def test_meaningful_comment_scores_low():
    c = _make_comment("# retry cap chosen empirically, see incident #482", code="MAX_RETRIES = 5")
    result = score_comment(c)
    assert result.score < 0.3
