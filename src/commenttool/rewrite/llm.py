"""
LLM rewrite layer.

Design choices worth keeping in mind when you extend this:

- The model NEVER receives code as editable input. It receives the comment
  text plus read-only code context, and returns only replacement comment
  text. We enforce "model only touches comments" structurally in
  rewrite/apply.py by splicing text back in at the comment's original byte
  span -- the model's output is never trusted to specify *where* to put
  anything.

- Classification and rewriting happen in one call with structured JSON
  output (skip / new_text / reason), rather than two separate calls, to
  keep cost down. If you want an audit trail of "the model considered this
  and chose not to touch it," that's exactly what `skip: true` + `reason`
  gives you -- it's not just a heuristic-only decision.

- Batching: one API call per comment is simplest but wasteful for repos
  with hundreds of flagged comments in the same file. batch_rewrite() below
  groups comments by file and sends them in a single call per file (capped
  at BATCH_SIZE) so the model also gets more style context for free.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from ..models import Comment, FlagResult, Rewrite

BATCH_SIZE = 20  # max comments per single API call, to keep prompts + outputs bounded

SYSTEM_PROMPT = """You are rewriting source code comments to be concise, useful, and free of \
AI-generated boilerplate. You will be shown one or more flagged comments, each with the \
code it is attached to, and (when available) a few sample comments from elsewhere in the \
file to match voice/style.

Rules:
- Output ONLY comment text. Never suggest changes to code.
- Cut restatement of what the code obviously does.
- Preserve or add "why" reasoning ONLY if it is inferable from context. Never invent facts, \
numbers, ticket references, or authorship you cannot see.
- Match the surrounding file's comment voice (terse vs. descriptive, punctuation habits, \
capitalization) based on the style samples given.
- Preserve the original comment delimiter style (//, #, /* */) -- return the FULL comment \
text including delimiters, ready to splice in verbatim.
- If a comment is already fine and shouldn't change, set skip=true and leave new_text empty.
- If you cannot improve it without inventing information, set skip=true rather than guessing.

Respond with ONLY a JSON array, no prose, no markdown fences. One object per input comment, \
in the same order, with this shape:
{"index": <int>, "skip": <bool>, "new_text": "<string>", "reason": "<short string>"}
"""


@dataclass
class LLMConfig:
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 4000
    style_samples: int = 3


class RewriteClient:
    """Thin wrapper around the Anthropic client. Import of `anthropic` is
    deferred to __init__ so the rest of the package works without the
    dependency installed (e.g. running just the filter/extract layers)."""

    def __init__(self, config: LLMConfig | None = None, api_key: str | None = None):
        import anthropic  # deferred import, see docstring

        self.config = config or LLMConfig()
        self._client = anthropic.Anthropic(api_key=api_key)  # picks up ANTHROPIC_API_KEY if None

    def rewrite_batch(
        self,
        flags: list[FlagResult],
        style_samples: list[str] | None = None,
    ) -> list[Rewrite]:
        """Rewrite a batch of flagged comments from the SAME file in one call.

        Callers are responsible for chunking into groups of <= BATCH_SIZE
        (see batch_by_file below) and for only passing comments from a
        single file, since style_samples and file-level context assume that.
        """
        if not flags:
            return []
        if len(flags) > BATCH_SIZE:
            raise ValueError(f"rewrite_batch got {len(flags)} comments, max is {BATCH_SIZE}; chunk first")

        prompt = self._build_prompt(flags, style_samples or [])
        response = self._client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        return self._parse_response(text, flags)

    def _build_prompt(self, flags: list[FlagResult], style_samples: list[str]) -> str:
        parts = []
        if style_samples:
            parts.append("Style samples from elsewhere in this file (for voice matching only):")
            for s in style_samples[: self.config.style_samples]:
                parts.append(f"  {s!r}")
            parts.append("")

        parts.append(f"File: {flags[0].comment.file_path}")
        parts.append(f"{len(flags)} flagged comment(s) to review:\n")

        for i, flag in enumerate(flags):
            c = flag.comment
            parts.append(f"--- Comment {i} ---")
            parts.append(f"Flagged for: {', '.join(flag.reasons) or 'general review'}")
            parts.append(f"Current text: {c.text!r}")
            if c.context:
                parts.append(f"Attached to ({c.context.node_type}, lines {c.context.start_line}-{c.context.end_line}):")
                parts.append(c.context.node_text)
            parts.append("")

        return "\n".join(parts)

    def _parse_response(self, text: str, flags: list[FlagResult]) -> list[Rewrite]:
        text = text.strip()
        # tolerate accidental markdown fencing despite instructions
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"model did not return valid JSON: {e}\nraw: {text[:500]}") from e

        rewrites: list[Rewrite] = []
        for item in parsed:
            idx = item["index"]
            if idx < 0 or idx >= len(flags):
                continue
            if item.get("skip"):
                continue
            comment = flags[idx].comment
            new_text = item.get("new_text", "").strip()
            if not new_text:
                continue
            rewrites.append(Rewrite(comment=comment, new_text=new_text, reason=item.get("reason", "")))
        return rewrites


def batch_by_file(flags: list[FlagResult]) -> dict:
    """Group flags by file path, chunked to BATCH_SIZE, ready for rewrite_batch()."""
    by_file: dict = {}
    for flag in flags:
        by_file.setdefault(flag.comment.file_path, []).append(flag)

    chunked: dict = {}
    for path, file_flags in by_file.items():
        chunks = [file_flags[i:i + BATCH_SIZE] for i in range(0, len(file_flags), BATCH_SIZE)]
        chunked[path] = chunks
    return chunked


def collect_style_samples(all_comments: list[Comment], flagged_ids: set[str], limit: int = 3) -> list[str]:
    """Pick a few UN-flagged, human-looking comments from the same file to use
    as style anchors. Falls back to an empty list if the file has too few
    (a 1-2 comment sample is noise, not a style -- see design notes)."""
    candidates = [c.text.strip() for c in all_comments if c.id not in flagged_ids and len(c.text.strip()) > 5]
    if len(candidates) < 2:
        return []
    return candidates[:limit]
