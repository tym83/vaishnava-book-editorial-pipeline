#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Batch pipeline for Vedabase scripture reference cleanup in DOCX files."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from docx_comment_applier import apply_comments
from docx_scripture_reference_normalizer import (
    cleanup_temp as cleanup_normalizer_temp,
    process_docx,
    resolve_docx,
    write_report_md as write_normalizer_report_md,
)
from review_issue_bundle import bundle_from_reference_scan
from review_issue_utils import write_json
from vedabase_reference_resolver import (
    resolve_vedabase_root_arg,
    scan_input_for_references,
    write_report_md as write_reference_scan_md,
)


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def count_format_candidates(scan_summary: Dict[str, object]) -> int:
    references = scan_summary.get("references")
    if not isinstance(references, list):
        return 0
    return sum(
        1
        for item in references
        if isinstance(item, dict) and item.get("resolved") and item.get("needs_normalization")
    )


def find_input_files(input_path: Path, *, output_root: Path, include_doc: bool) -> Tuple[Path, List[Path]]:
    output_root_resolved = output_root.resolve()
    if input_path.is_file():
        suffix = input_path.suffix.lower()
        allowed = {".docx"}
        if include_doc:
            allowed.add(".doc")
        if suffix not in allowed:
            die(f"Unsupported input file: {input_path}")
        return input_path.parent, [input_path]

    if not input_path.is_dir():
        die(f"Input path not found: {input_path}")

    patterns = ["*.docx"]
    if include_doc:
        patterns.append("*.doc")

    files: List[Path] = []
    for pattern in patterns:
        for candidate in input_path.rglob(pattern):
            try:
                if candidate.resolve().is_relative_to(output_root_resolved):
                    continue
            except FileNotFoundError:
                continue
            files.append(candidate)
    unique_sorted = sorted({path.resolve(): path for path in files}.values())
    return input_path, unique_sorted


def item_artifact_dir(input_path: Path, *, input_root: Path, output_root: Path) -> Path:
    if input_path.is_relative_to(input_root):
        relative = input_path.relative_to(input_root)
    else:
        relative = Path(input_path.name)
    return output_root / "items" / relative.parent / input_path.stem


def write_scan_reports(scan_summary: Dict[str, object], json_path: Path, md_path: Path) -> None:
    write_json(json_path, scan_summary)
    write_reference_scan_md(md_path, scan_summary)


def write_queue_markdown(path: Path, queue_items: List[Dict[str, object]]) -> None:
    lines = [
        "# Editorial Queue\n",
        "\n",
        f"- files: {len(queue_items)}\n",
        "\n",
    ]
    for item in queue_items:
        lines.append(f"## {item['relative_path']}\n\n")
        lines.append(f"- unresolved_after: {item['unresolved_after']}\n")
        if item.get("unresolved_bundle_path"):
            lines.append(f"- bundle: `{item['unresolved_bundle_path']}`\n")
        if item.get("commented_docx_path"):
            lines.append(f"- commented_docx: `{item['commented_docx_path']}`\n")
        lines.append("\n")
    path.write_text("".join(lines), encoding="utf-8")


def write_index_markdown(path: Path, summary: Dict[str, object]) -> None:
    lines = [
        "# DOCX Scripture Reference Pipeline\n",
        "\n",
        f"Generated: `{summary['generated_at']}`\n",
        "\n",
        f"- input_root: `{summary['input_root']}`\n",
        f"- output_root: `{summary['output_root']}`\n",
        f"- vedabase_root: `{summary['vedabase_root']}`\n",
        f"- files_total: {summary['files_total']}\n",
        f"- files_with_references: {summary['files_with_references']}\n",
        f"- files_normalized: {summary['files_normalized']}\n",
        f"- files_in_editorial_queue: {summary['files_in_editorial_queue']}\n",
        f"- files_with_errors: {summary['files_with_errors']}\n",
        f"- references_before: {summary['reference_count_before_total']}\n",
        f"- format_candidates_before: {summary['format_candidates_before_total']}\n",
        f"- unresolved_before: {summary['unresolved_before_total']}\n",
        f"- references_after: {summary['reference_count_after_total']}\n",
        f"- format_candidates_after: {summary['format_candidates_after_total']}\n",
        f"- unresolved_after: {summary['unresolved_after_total']}\n",
        f"- replacements: {summary['normalizer_replacements_total']}\n",
        "\n",
        "## Files\n",
        "\n",
    ]
    for item in summary["items"]:
        lines.append(f"### {item['relative_path']}\n\n")
        lines.append(f"- status: `{item['status']}`\n")
        if item.get("error"):
            lines.append(f"- error: `{item['error']}`\n")
        lines.append(f"- references_before: {item['reference_count_before']}\n")
        lines.append(f"- format_candidates_before: {item['format_candidates_before']}\n")
        lines.append(f"- unresolved_before: {item['unresolved_before']}\n")
        if item.get("normalized_docx_path"):
            lines.append(f"- normalized_docx: `{item['normalized_docx_path']}`\n")
            lines.append(f"- replacements: {item['normalizer_replacements']}\n")
            lines.append(f"- references_after: {item['reference_count_after']}\n")
            lines.append(f"- format_candidates_after: {item['format_candidates_after']}\n")
            lines.append(f"- unresolved_after: {item['unresolved_after']}\n")
        if item.get("unresolved_bundle_path"):
            lines.append(f"- unresolved_bundle: `{item['unresolved_bundle_path']}`\n")
        if item.get("commented_docx_path"):
            lines.append(f"- commented_docx: `{item['commented_docx_path']}`\n")
        lines.append("\n")
    path.write_text("".join(lines), encoding="utf-8")


def process_one_file(
    input_path: Path,
    *,
    input_root: Path,
    output_root: Path,
    vedabase_root: Path,
    locale: str,
    apply_comment_queue: bool,
    author: str,
    initials: str,
) -> Dict[str, object]:
    artifact_dir = item_artifact_dir(input_path, input_root=input_root, output_root=output_root)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    relative_path = input_path.relative_to(input_root) if input_path.is_relative_to(input_root) else Path(input_path.name)

    item: Dict[str, object] = {
        "input_path": str(input_path),
        "relative_path": relative_path.as_posix(),
        "artifact_dir": str(artifact_dir),
        "status": "pending",
        "reference_count_before": 0,
        "format_candidates_before": 0,
        "unresolved_before": 0,
        "normalizer_replacements": 0,
        "reference_count_after": 0,
        "format_candidates_after": 0,
        "unresolved_after": 0,
        "normalized_docx_path": "",
        "unresolved_bundle_path": "",
        "commented_docx_path": "",
        "error": "",
    }

    pre_scan = scan_input_for_references(
        input_path,
        vedabase_root=vedabase_root,
        locale=locale,
        include_sections=False,
    )
    write_scan_reports(pre_scan, artifact_dir / "pre_scan.json", artifact_dir / "pre_scan.md")

    item["reference_count_before"] = int(pre_scan.get("reference_count", 0))
    item["format_candidates_before"] = count_format_candidates(pre_scan)
    item["unresolved_before"] = int(pre_scan.get("unresolved_count", 0))

    if item["reference_count_before"] == 0:
        item["status"] = "no_references"
        return item

    src_docx, temp_dir = resolve_docx(input_path)
    normalized_path = artifact_dir / f"{input_path.stem}.normalized.docx"
    try:
        normalization_summary = process_docx(src_docx, normalized_path)
    finally:
        cleanup_normalizer_temp(temp_dir)

    write_json(artifact_dir / "normalization.json", normalization_summary)
    write_normalizer_report_md(artifact_dir / "normalization.md", normalization_summary)
    item["normalized_docx_path"] = str(normalized_path)
    item["normalizer_replacements"] = int(normalization_summary.get("match_replacements", 0))

    post_scan = scan_input_for_references(
        normalized_path,
        vedabase_root=vedabase_root,
        locale=locale,
        include_sections=False,
    )
    write_scan_reports(post_scan, artifact_dir / "post_scan.json", artifact_dir / "post_scan.md")

    item["reference_count_after"] = int(post_scan.get("reference_count", 0))
    item["format_candidates_after"] = count_format_candidates(post_scan)
    item["unresolved_after"] = int(post_scan.get("unresolved_count", 0))

    unresolved_bundle = bundle_from_reference_scan(
        artifact_dir / "post_scan.json",
        "docx",
        str(normalized_path),
        "main_story",
        unresolved_only=True,
    )
    unresolved_bundle_path = artifact_dir / "unresolved_bundle.json"
    write_json(unresolved_bundle_path, unresolved_bundle)
    if unresolved_bundle.get("issues"):
        item["unresolved_bundle_path"] = str(unresolved_bundle_path)
        item["status"] = "editorial_queue"
        if apply_comment_queue:
            commented_docx_path = artifact_dir / f"{input_path.stem}.editorial-comments.docx"
            apply_comments(
                normalized_path,
                unresolved_bundle_path,
                commented_docx_path,
                author,
                initials,
                artifact_dir / "comment_apply.json",
                artifact_dir / "comment_apply.md",
            )
            item["commented_docx_path"] = str(commented_docx_path)
    else:
        item["status"] = "clean"
    return item


def run_pipeline(
    input_path: Path,
    output_root: Path,
    *,
    vedabase_root: Path,
    locale: str,
    include_doc: bool,
    apply_comment_queue: bool,
    author: str,
    initials: str,
) -> Dict[str, object]:
    input_root, files = find_input_files(input_path, output_root=output_root, include_doc=include_doc)
    output_root.mkdir(parents=True, exist_ok=True)

    items: List[Dict[str, object]] = []
    for path in files:
        try:
            items.append(
                process_one_file(
                    path,
                    input_root=input_root,
                    output_root=output_root,
                    vedabase_root=vedabase_root,
                    locale=locale,
                    apply_comment_queue=apply_comment_queue,
                    author=author,
                    initials=initials,
                )
            )
        except Exception as exc:  # pragma: no cover - defensive batch behavior
            relative_path = path.relative_to(input_root) if path.is_relative_to(input_root) else Path(path.name)
            artifact_dir = item_artifact_dir(path, input_root=input_root, output_root=output_root)
            artifact_dir.mkdir(parents=True, exist_ok=True)
            item = {
                "input_path": str(path),
                "relative_path": relative_path.as_posix(),
                "artifact_dir": str(artifact_dir),
                "status": "error",
                "reference_count_before": 0,
                "format_candidates_before": 0,
                "unresolved_before": 0,
                "normalizer_replacements": 0,
                "reference_count_after": 0,
                "format_candidates_after": 0,
                "unresolved_after": 0,
                "normalized_docx_path": "",
                "unresolved_bundle_path": "",
                "commented_docx_path": "",
                "error": f"{type(exc).__name__}: {exc}",
            }
            write_json(artifact_dir / "error.json", item)
            items.append(item)

    queue_items = [item for item in items if item["status"] == "editorial_queue"]
    summary = {
        "generated_at": iso_now(),
        "input_root": str(input_root),
        "output_root": str(output_root),
        "vedabase_root": str(vedabase_root),
        "locale": locale,
        "files_total": len(items),
        "files_with_references": sum(1 for item in items if item["reference_count_before"] > 0),
        "files_normalized": sum(1 for item in items if item["normalized_docx_path"]),
        "files_in_editorial_queue": len(queue_items),
        "files_with_errors": sum(1 for item in items if item["status"] == "error"),
        "reference_count_before_total": sum(int(item["reference_count_before"]) for item in items),
        "format_candidates_before_total": sum(int(item["format_candidates_before"]) for item in items),
        "unresolved_before_total": sum(int(item["unresolved_before"]) for item in items),
        "reference_count_after_total": sum(int(item["reference_count_after"]) for item in items),
        "format_candidates_after_total": sum(int(item["format_candidates_after"]) for item in items),
        "unresolved_after_total": sum(int(item["unresolved_after"]) for item in items),
        "normalizer_replacements_total": sum(int(item["normalizer_replacements"]) for item in items),
        "items": items,
    }
    queue_payload = {
        "generated_at": summary["generated_at"],
        "output_root": summary["output_root"],
        "items": queue_items,
    }

    write_json(output_root / "index.json", summary)
    write_index_markdown(output_root / "index.md", summary)
    write_json(output_root / "editorial_queue.json", queue_payload)
    write_queue_markdown(output_root / "editorial_queue.md", queue_items)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch pipeline for Vedabase scripture references in DOCX")
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("input")
    run_cmd.add_argument("output_root")
    run_cmd.add_argument("--vedabase-root")
    run_cmd.add_argument("--locale", default="ru")
    run_cmd.add_argument("--include-doc", action="store_true")
    run_cmd.add_argument("--apply-comments", action="store_true")
    run_cmd.add_argument("--author", default="Codex")
    run_cmd.add_argument("--initials", default="CX")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "run":
        parser.error("Unknown command")
        return 2

    input_path = Path(args.input)
    output_root = Path(args.output_root)
    vedabase_root = resolve_vedabase_root_arg(args.vedabase_root, fallback_input=input_path)
    summary = run_pipeline(
        input_path,
        output_root,
        vedabase_root=vedabase_root,
        locale=args.locale,
        include_doc=args.include_doc,
        apply_comment_queue=args.apply_comments,
        author=args.author,
        initials=args.initials,
    )
    print(
        json.dumps(
            {
                "output_root": str(output_root),
                "files_total": summary["files_total"],
                "files_in_editorial_queue": summary["files_in_editorial_queue"],
                "files_with_errors": summary["files_with_errors"],
                "unresolved_after_total": summary["unresolved_after_total"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
