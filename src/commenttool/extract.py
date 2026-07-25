"""
Walks a source file's tree-sitter AST and extracts Comment objects, each
paired with the code it's attached to.

Attachment is inferred, not given by tree-sitter (comments are just leaf
nodes with no semantic link to nearby code). The rule, in order:

  1. TRAILING — the comment starts on the same source line as the end of
     the previous named sibling. ("x = 5  // why 5")
  2. LEADING  — the comment is immediately followed (allowing blank-line-free
     gap) by a named sibling; that sibling is the attachment target.
     ("// why we do this\ndef f(): ...")
  3. INTERNAL — the comment's parent is a block/body node but neither of the
     above applies cleanly (e.g. comment is the last thing in a block).
  4. DANGLING — no reasonable target found (e.g. comment is alone in the file
     or at EOF with nothing before or after it).

CONTEXT_MAX_CHARS caps how much of the attached node's source we carry
around, so a comment sitting above a 400-line function doesn't blow up
prompt size later.
"""
from __future__ import annotations

from pathlib import Path

from tree_sitter_languages import get_parser

from .languages import LangConfig, config_for_path
from .models import AttachmentKind, CodeContext, Comment, CommentStyle

CONTEXT_MAX_CHARS = 1200


def extract_comments(file_path: Path, source: bytes) -> list[Comment]:
    """Extract all comments from a file, with inferred code attachment.

    Returns an empty list for unsupported file types rather than raising,
    since callers typically walk a whole repo and want to skip silently.
    """
    lang_config = config_for_path(file_path)
    if lang_config is None:
        return []

    parser = get_parser(lang_config.ts_name)
    tree = parser.parse(source)
    root = tree.root_node

    comment_nodes = _collect_comment_nodes(root, lang_config)
    comments: list[Comment] = []
    for node in comment_nodes:
        style = _classify_style(node, lang_config, source)
        attachment, context_node = _infer_attachment(node, source)
        context = _build_context(context_node, source) if context_node else None
        comments.append(
            Comment(
                file_path=file_path,
                language=lang_config.ts_name,
                text=source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"),
                start_byte=node.start_byte,
                end_byte=node.end_byte,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                style=style,
                attachment=attachment,
                context=context,
            )
        )
    return comments


def _collect_comment_nodes(root, lang_config: LangConfig) -> list:
    """Depth-first walk collecting every node whose type is a comment type."""
    out = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type in lang_config.comment_node_types:
            out.append(node)
        stack.extend(node.children)
    out.sort(key=lambda n: n.start_byte)
    return out


def _classify_style(node, lang_config: LangConfig, source: bytes) -> CommentStyle:
    text = source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
    if lang_config.block_delims and text.startswith(lang_config.block_delims[0]):
        return CommentStyle.BLOCK
    if "\n" in text:
        return CommentStyle.BLOCK
    return CommentStyle.LINE


def _infer_attachment(comment_node, source: bytes):
    """Return (AttachmentKind, target_node_or_None).

    target_node is the code node the comment is "about" — used to build
    CodeContext. May be None for DANGLING.
    """
    parent = comment_node.parent
    if parent is None:
        return AttachmentKind.DANGLING, None

    siblings = [c for c in parent.children if c.type != "comment"]
    comment_line = comment_node.end_point[0]

    # TRAILING: is there a named sibling ending on the same line, right before us?
    prev_sib = _previous_named_sibling(comment_node)
    if prev_sib is not None and prev_sib.end_point[0] == comment_node.start_point[0]:
        return AttachmentKind.TRAILING, prev_sib

    # LEADING: is there a named sibling starting shortly after us (allow one blank line)?
    next_sib = _next_named_sibling(comment_node)
    if next_sib is not None and (next_sib.start_point[0] - comment_node.end_point[0]) <= 2:
        return AttachmentKind.LEADING, next_sib

    # INTERNAL: comment lives inside a block-like parent but isn't cleanly bound
    if parent.type.endswith("block") or parent.type.endswith("body") or parent.type == "module":
        # best-effort context: use the parent itself, truncated, so the LLM
        # still has *something* to reason about
        return AttachmentKind.INTERNAL, parent

    return AttachmentKind.DANGLING, None


def _previous_named_sibling(node):
    sib = node.prev_named_sibling
    return sib


def _next_named_sibling(node):
    sib = node.next_named_sibling
    return sib


def _build_context(node, source: bytes) -> CodeContext:
    text = source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
    truncated = text if len(text) <= CONTEXT_MAX_CHARS else text[:CONTEXT_MAX_CHARS] + "\n...[truncated]"
    return CodeContext(
        node_type=node.type,
        node_text=truncated,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
    )
