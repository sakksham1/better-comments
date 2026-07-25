# commenttool

Flags redundant / AI-smelling comments in a repo and rewrites them via an
LLM, with output as a reviewable diff — never a silent in-place mutation.

## Status

v0 scaffold. Core pipeline (parse → filter → rewrite → diff) is wired up
end to end for Python, JS/TS, Go, Rust, Java, C/C++, and Ruby. Not yet
published; install locally to develop.

## Install (dev)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=sk-...   # only needed for --llm
```

## Usage

```bash
# Free, instant: heuristic-only pass, no API calls. Good for sanity-checking
# the filter before spending any budget.
commenttool scan ./src

# Full pipeline: flag + LLM rewrite + write a patch file
commenttool scan ./src --llm --out changes.patch

# Review like any other diff
git apply --check changes.patch   # or: commenttool apply --diff changes.patch --check
git apply changes.patch
git diff
```

Tune sensitivity with `--confidence` (0.0-1.0, default 0.4 — lower = more
comments flagged). Run `commenttool scan --help` for the rest.

## Architecture

```
extract.py      tree-sitter parsing + comment→code attachment inference
filters/        cheap heuristics that decide what's worth an LLM call
rewrite/llm.py  prompt + structured-output call to the model
rewrite/apply.py  byte-offset splicing — the ONLY place file content is
                   mutated, and it only ever touches comment spans
diffing.py      unified diff generation from (original, rewritten) bytes
cache.py        file-hash cache so unchanged files are skipped on rescans
cli.py          `scan` / `apply` commands
```

Design invariants worth preserving as you extend this:

- **The model never sees code as editable input.** It gets comment text +
  read-only code context, returns replacement comment text, and
  `rewrite/apply.py` splices it back at the comment's original byte span.
  This is enforced structurally, not by prompting alone.
- **Diff-first, never silent-mutate.** `scan --out` writes a patch; nothing
  touches working files directly. If you add an `--in-place` flag later,
  keep diff-mode as the default.
- **Heuristics gate LLM calls, they don't replace judgment.** `filters/heuristics.py`
  is intentionally over-inclusive — it exists to cut cost, not to be the
  final word. The LLM step can (and should) `skip: true` things the
  heuristic flagged.
- **tree-sitter-language-pack fetches parsers on first use.** Each language's
  parser downloads from the network the first time you scan a file of that
  type, then caches locally. First run on a polyglot repo needs
  connectivity; every run after is offline.

## Not yet built (see original design doc)

- Pre-commit hook / CI check that only scans PR diffs instead of the whole repo
- Per-language comment-attachment refinements beyond the current sibling-based heuristic
- `.commenttool.toml` config file (currently CLI flags only)
- Style-guide injection (org-wide voice, beyond per-file sampling)
- Multi-file batching to reduce API round-trips further

## Testing

```bash
pytest
```
