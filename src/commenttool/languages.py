"""
Per-language configuration for the tree-sitter layer.

Every language grammar names its comment node(s) slightly differently, and
line-comment delimiters differ too. This module is the single place that
knows about those differences, so extract.py and rewrite/apply.py stay
language-agnostic.

Uses `tree_sitter_language_pack` (the maintained successor to the now-defunct
`tree_sitter_languages`), which ships 300+ grammars behind one API and
supports current Python (3.10-3.14). Parsers are fetched on first use per
language and cached locally, so we don't need to vendor/compile grammars
ourselves -- the tradeoff is that the very first parse of a given language
needs network access.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LangConfig:
    ts_name: str                       # name tree_sitter_language_pack.get_parser() expects
    comment_node_types: frozenset[str]  # tree-sitter node type(s) that represent comments
    line_prefixes: tuple[str, ...] = field(default_factory=tuple)   # e.g. ("#",)
    block_delims: tuple[str, str] | None = None                     # e.g. ("/*", "*/")
    # Node types treated as "structured docstring" and skipped by default
    # (JSDoc-style /** */, Python docstrings that look like param blocks, etc.)
    # This is a text-pattern hint, checked in filters/heuristics.py, not tree-sitter itself.
    structured_doc_hint: tuple[str, ...] = field(default_factory=tuple)


EXTENSION_TO_LANGUAGE: dict[str, LangConfig] = {
    ".py": LangConfig(
        ts_name="python",
        comment_node_types=frozenset({"comment"}),
        line_prefixes=("#",),
        structured_doc_hint=(":param", ":return", ":rtype", ":raises", "Args:", "Returns:"),
    ),
    ".js": LangConfig(
        ts_name="javascript",
        comment_node_types=frozenset({"comment"}),
        line_prefixes=("//",),
        block_delims=("/*", "*/"),
        structured_doc_hint=("@param", "@returns", "@type", "@throws"),
    ),
    ".jsx": LangConfig(
        ts_name="javascript",
        comment_node_types=frozenset({"comment"}),
        line_prefixes=("//",),
        block_delims=("/*", "*/"),
        structured_doc_hint=("@param", "@returns", "@type", "@throws"),
    ),
    ".ts": LangConfig(
        ts_name="typescript",
        comment_node_types=frozenset({"comment"}),
        line_prefixes=("//",),
        block_delims=("/*", "*/"),
        structured_doc_hint=("@param", "@returns", "@type", "@throws"),
    ),
    ".tsx": LangConfig(
        ts_name="tsx",
        comment_node_types=frozenset({"comment"}),
        line_prefixes=("//",),
        block_delims=("/*", "*/"),
        structured_doc_hint=("@param", "@returns", "@type", "@throws"),
    ),
    ".go": LangConfig(
        ts_name="go",
        comment_node_types=frozenset({"comment"}),
        line_prefixes=("//",),
        block_delims=("/*", "*/"),
    ),
    ".rs": LangConfig(
        ts_name="rust",
        comment_node_types=frozenset({"line_comment", "block_comment"}),
        line_prefixes=("//", "///", "//!"),
        block_delims=("/*", "*/"),
    ),
    ".java": LangConfig(
        ts_name="java",
        comment_node_types=frozenset({"line_comment", "block_comment"}),
        line_prefixes=("//",),
        block_delims=("/*", "*/"),
        structured_doc_hint=("@param", "@return", "@throws"),
    ),
    ".c": LangConfig(
        ts_name="c",
        comment_node_types=frozenset({"comment"}),
        line_prefixes=("//",),
        block_delims=("/*", "*/"),
    ),
    ".h": LangConfig(
        ts_name="c",
        comment_node_types=frozenset({"comment"}),
        line_prefixes=("//",),
        block_delims=("/*", "*/"),
    ),
    ".cpp": LangConfig(
        ts_name="cpp",
        comment_node_types=frozenset({"comment"}),
        line_prefixes=("//",),
        block_delims=("/*", "*/"),
    ),
    ".hpp": LangConfig(
        ts_name="cpp",
        comment_node_types=frozenset({"comment"}),
        line_prefixes=("//",),
        block_delims=("/*", "*/"),
    ),
    ".rb": LangConfig(
        ts_name="ruby",
        comment_node_types=frozenset({"comment"}),
        line_prefixes=("#",),
    ),
}


def config_for_path(path) -> LangConfig | None:
    """Return the LangConfig for a file path's extension, or None if unsupported."""
    suffix = getattr(path, "suffix", None)
    if suffix is None:
        from pathlib import Path
        suffix = Path(path).suffix
    return EXTENSION_TO_LANGUAGE.get(suffix)


def is_supported(path) -> bool:
    return config_for_path(path) is not None
