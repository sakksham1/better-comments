"""
First-pass filter: cheap, deterministic heuristics that decide which comments
are worth sending to an LLM at all. This is deliberately conservative-leaning
toward *flagging* — the LLM classification step (rewrite/llm.py) makes the
final call on whether to actually rewrite. The point of this layer is purely
to cut volume/cost, not to be the source of truth.

score_comment() returns a FlagResult with a 0.0-1.0 score and human-readable
reasons, so `commenttool scan` can print *why* something was flagged and a
user can sanity check the heuristics before trusting the tool.
"""
from __future__ import annotations

import re

from ..languages import config_for_path
from ..models import Comment, FlagResult

# Phrases that skew towards LLM-generated boilerplate. Matched case-insensitively.
AI_TELL_PATTERNS = [
    re.compile(r"\bthis function is responsible for\b", re.I),
    re.compile(r"\bthis method (?:is used to|handles)\b", re.I),
    re.compile(r"^\s*note:\s", re.I | re.M),
    re.compile(r"^\s*step \d+[:.]", re.I | re.M),
    re.compile(r"^\s*\d+\.\s+\w+", re.M),          # numbered list "1. Do X"
    re.compile(r"\bit(?:'s| is) (?:important|worth noting) that\b", re.I),
    re.compile(r"\bin order to\b", re.I),
    re.compile(r"\bthis (?:will|helps to|ensures that)\b", re.I),
    re.compile(r"\bfor (?:example|instance),?\s+(?:if|suppose)\b", re.I),
]

# Comments that should never be flagged regardless of content.
SKIP_PATTERNS = [
    re.compile(r"\bcopyright\b", re.I),
    re.compile(r"\blicensed? under\b", re.I),
    re.compile(r"\bspdx-license-identifier\b", re.I),
    re.compile(r"\btodo\b", re.I),
    re.compile(r"\bfixme\b", re.I),
    re.compile(r"\bhack\b", re.I),
    re.compile(r"\bxxx\b", re.I),
]

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def should_skip(comment: Comment) -> str | None:
    """Return a skip reason string, or None if the comment should be considered.

    Handles: license/copyright headers, TODO/FIXME/HACK tags, and structured
    docstrings (JSDoc-style @param blocks, Sphinx-style :param: blocks) —
    all deliberately out of scope per the tool's design.
    """
    text = comment.text

    for pattern in SKIP_PATTERNS:
        if pattern.search(text):
            return f"matches skip pattern: {pattern.pattern}"

    lang_config = config_for_path(comment.file_path)
    if lang_config and lang_config.structured_doc_hint:
        for hint in lang_config.structured_doc_hint:
            if hint in text:
                return f"structured docstring (contains '{hint}')"

    # Very short comments (single word, punctuation) aren't worth touching.
    stripped = _strip_delimiters(text)
    if len(stripped.strip()) <= 2:
        return "too short to meaningfully rewrite"

    return None


def score_comment(comment: Comment) -> FlagResult:
    """Score a comment 0.0-1.0 on likelihood of being redundant / AI-slop.

    This does NOT check should_skip() — callers must call should_skip()
    first and only call score_comment() for comments that pass.
    """
    reasons: list[str] = []
    score = 0.0

    text = _strip_delimiters(comment.text)

    # --- AI-tell phrasing ---
    tell_hits = [p.pattern for p in AI_TELL_PATTERNS if p.search(text)]
    if tell_hits:
        score += min(0.5, 0.2 * len(tell_hits))
        reasons.append(f"AI-tell phrasing ({len(tell_hits)} match{'es' if len(tell_hits) > 1 else ''})")

    # --- Restates the code (token overlap with attached code) ---
    if comment.context is not None:
        overlap = _token_overlap_ratio(text, comment.context.node_text)
        if overlap > 0.6:
            score += 0.4
            reasons.append(f"high token overlap with code ({overlap:.0%})")
        elif overlap > 0.4:
            score += 0.2
            reasons.append(f"moderate token overlap with code ({overlap:.0%})")

    # --- Verbose relative to what it's attached to ---
    if comment.context is not None:
        code_lines = max(1, comment.context.end_line - comment.context.start_line + 1)
        comment_lines = max(1, comment.end_line - comment.start_line + 1)
        if code_lines <= 2 and comment_lines >= 2:
            score += 0.15
            reasons.append("multi-line comment on trivial (<=2 line) code")
        if len(text) > 200 and code_lines <= 3:
            score += 0.15
            reasons.append("long comment on short code block")

    # --- Excessive hedging ---
    hedges = len(re.findall(r"\b(?:might|maybe|probably|could potentially|it seems)\b", text, re.I))
    if hedges >= 2:
        score += 0.1
        reasons.append(f"excessive hedging ({hedges} instances)")

    return FlagResult(comment=comment, score=min(score, 1.0), reasons=reasons)


def _strip_delimiters(text: str) -> str:
    """Best-effort removal of comment delimiters for text-analysis purposes."""
    stripped = text.strip()
    for prefix in ("///", "//!", "//", "#", "--"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):]
            break
    else:
        if stripped.startswith("/*"):
            stripped = stripped[2:]
        if stripped.endswith("*/"):
            stripped = stripped[:-2]
    # strip leading "*" on each line (common in block comments)
    lines = [re.sub(r"^\s*\*\s?", "", ln) for ln in stripped.splitlines()]
    return "\n".join(lines).strip()


def _token_overlap_ratio(comment_text: str, code_text: str) -> float:
    """Fraction of the comment's identifier-like tokens that also appear in the code."""
    comment_tokens = {t.lower() for t in _WORD_RE.findall(comment_text) if len(t) > 2}
    if not comment_tokens:
        return 0.0
    code_tokens = {t.lower() for t in _WORD_RE.findall(code_text)}
    shared = comment_tokens & code_tokens
    return len(shared) / len(comment_tokens)
