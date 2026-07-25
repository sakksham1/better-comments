"""
CLI entrypoint.

  commenttool scan ./src                      # report flagged comments, no LLM calls
  commenttool scan ./src --llm --out out.patch # flag + rewrite + write a reviewable diff
  commenttool apply --diff out.patch           # git apply the patch (after you've reviewed it)

`scan` without --llm is intentionally free/instant -- it's the heuristic
layer only, meant for eyeballing what the tool *would* flag before you spend
any API budget on rewrites.
"""
from __future__ import annotations

import json as json_module
import subprocess
import sys
from pathlib import Path

import click

from .cache import ScanCache, hash_content
from .config import ScanConfig
from .diffing import combine_diffs, make_file_diff
from .extract import extract_comments
from .filters import score_comment, should_skip
from .models import FileResult
from .repo import iter_source_files
from .rewrite.apply import splice_rewrites


@click.group()
def main():
    """AI-assisted comment cleanup: flag redundant/AI-smelling comments, rewrite via diff review."""


@main.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--confidence", default=0.4, show_default=True, help="Min score (0-1) to flag a comment.")
@click.option("--no-cache", is_flag=True, help="Ignore the file-hash cache; re-scan everything.")
@click.option("--llm", is_flag=True, help="Also run the LLM rewrite step (costs API calls).")
@click.option("--model", default="claude-sonnet-4-6", show_default=True, help="Model to use with --llm.")
@click.option("--out", type=click.Path(path_type=Path), default=None, help="Write a unified diff patch here (requires --llm).")
@click.option("--json", "json_out", type=click.Path(path_type=Path), default=None, help="Write flag report as JSON here.")
def scan(path: Path, confidence: float, no_cache: bool, llm: bool, model: str, out: Path | None, json_out: Path | None):
    """Scan PATH for flaggable comments, optionally rewriting via --llm."""
    config = ScanConfig(confidence=confidence, use_cache=not no_cache)
    cache = ScanCache(path) if config.use_cache else None

    results: list[FileResult] = []
    total_files = 0
    total_flagged = 0

    rewrite_client = None
    if llm:
        from .rewrite.llm import LLMConfig, RewriteClient

        rewrite_client = RewriteClient(LLMConfig(model=model))

    for file_path in iter_source_files(path, config):
        total_files += 1
        rel = str(file_path.relative_to(path))
        content = file_path.read_bytes()
        content_hash = hash_content(content)

        if cache and cache.is_unchanged(rel, content_hash):
            continue  # unchanged since last scan; skip re-parsing entirely

        comments = extract_comments(file_path, content)
        flags = []
        for comment in comments:
            skip_reason = should_skip(comment)
            if skip_reason:
                continue
            flag = score_comment(comment)
            if flag.score >= config.confidence:
                flags.append(flag)

        if cache:
            cache.update(rel, content_hash, len(flags))

        if not flags:
            continue

        total_flagged += len(flags)
        file_result = FileResult(file_path=file_path, file_hash=content_hash, flags=flags)

        if rewrite_client:
            from .rewrite.llm import batch_by_file, collect_style_samples

            flagged_ids = {f.comment.id for f in flags}
            samples = collect_style_samples(comments, flagged_ids)
            chunks = batch_by_file(flags).get(file_path, [])
            for chunk in chunks:
                file_result.rewrites.extend(rewrite_client.rewrite_batch(chunk, style_samples=samples))

        results.append(file_result)

    if cache:
        cache.save()

    _print_report(results, total_files, total_flagged)

    if json_out:
        json_out.write_text(_report_json(results))
        click.echo(f"JSON report written to {json_out}")

    if out:
        if not llm:
            click.echo("--out requires --llm (nothing to diff without rewrites)", err=True)
            sys.exit(1)
        diffs = []
        for r in results:
            if not r.rewrites:
                continue
            original = r.file_path.read_bytes()
            rewritten = splice_rewrites(original, r.rewrites)
            diffs.append(make_file_diff(r.file_path, original, rewritten))
        patch = combine_diffs(diffs)
        out.write_text(patch)
        click.echo(f"Patch written to {out} ({len(diffs)} file(s) changed)")


@main.command()
@click.option("--diff", "diff_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--check", is_flag=True, help="Dry-run: verify the patch applies cleanly without writing.")
def apply(diff_path: Path, check: bool):
    """Apply a patch produced by `scan --out`, via `git apply`."""
    cmd = ["git", "apply"]
    if check:
        cmd.append("--check")
    cmd.append(str(diff_path))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        click.echo(f"git apply failed:\n{result.stderr}", err=True)
        sys.exit(result.returncode)
    click.echo("Patch checks out cleanly, nothing written." if check else "Patch applied.")


def _print_report(results: list[FileResult], total_files: int, total_flagged: int) -> None:
    click.echo(f"Scanned {total_files} file(s), {total_flagged} comment(s) flagged.\n")
    for r in results:
        click.echo(f"{r.file_path}")
        for flag in r.flags:
            c = flag.comment
            click.echo(f"  L{c.start_line}: score={flag.score:.2f} [{', '.join(flag.reasons)}]")
            click.echo(f"    {c.text.strip()!r}")
        if r.rewrites:
            for rw in r.rewrites:
                click.echo(f"  -> rewrite: {rw.new_text.strip()!r}  ({rw.reason})")
        click.echo()


def _report_json(results: list[FileResult]) -> str:
    data = []
    for r in results:
        data.append({
            "file": str(r.file_path),
            "flags": [
                {
                    "line": f.comment.start_line,
                    "score": f.score,
                    "reasons": f.reasons,
                    "text": f.comment.text,
                }
                for f in r.flags
            ],
            "rewrites": [
                {"line": rw.comment.start_line, "new_text": rw.new_text, "reason": rw.reason}
                for rw in r.rewrites
            ],
        })
    return json_module.dumps(data, indent=2)


if __name__ == "__main__":
    main()
