#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""
Build a single editor-facing DOCX with all review layers as Word comments.

This is the final aggregation step for book-level review. It prevents the
editorial workflow from splitting proofreading/style comments and deep
translation-review comments across different DOCX versions.

Example:
  python3 scripts/all_review_docx_builder.py build \
    book.formatted.docx book.all-review.docx \
    review/style.bundle.json review/deep.bundle.json \
    --merged-bundle review/all-review.bundle.json \
    --report-json review/all-review.apply.json \
    --report-md review/all-review.apply.md \
    --legacy-copy book.review-comments.docx \
    --legacy-copy book.master-review.docx

By default, input_docx must be a clean formatted DOCX without existing
comments. This keeps repeated runs from silently duplicating comments.
"""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from lxml import etree

from docx_comment_applier import apply_comments
from review_issue_bundle import merge_bundles
from review_issue_utils import write_json


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def count_word_comments(docx_path: Path) -> int:
    with zipfile.ZipFile(docx_path, "r") as z:
        if "word/comments.xml" not in z.namelist():
            return 0
        root = etree.fromstring(z.read("word/comments.xml"))
    return len(root.findall("w:comment", namespaces=NS))


def has_existing_comments(docx_path: Path) -> bool:
    return count_word_comments(docx_path) > 0


def copy_if_requested(source: Path, destinations: Sequence[Path]) -> List[str]:
    copied: List[str] = []
    source_resolved = source.resolve()
    for destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.resolve() == source_resolved:
            continue
        shutil.copy2(source, destination)
        copied.append(str(destination))
    return copied


def write_markdown_report(path: Path, summary: Dict[str, object]) -> None:
    lines = [
        "# All-Review DOCX Build Report",
        "",
        f"Input: `{summary['input_docx']}`",
        f"Output: `{summary['output_docx']}`",
        f"Merged bundle: `{summary['merged_bundle']}`",
        "",
        f"- input bundles: {summary['input_bundle_count']}",
        f"- issues: {summary['issue_count']}",
        f"- applied: {summary['applied']}",
        f"- skipped: {summary['skipped']}",
        f"- Word comments in output: {summary['word_comment_count']}",
        "",
        "## Legacy Copies",
    ]
    legacy_copies = summary.get("legacy_copies") or []
    if legacy_copies:
        lines.extend(f"- `{item}`" for item in legacy_copies)
    else:
        lines.append("- none")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_all_review_docx(
    input_docx: Path,
    output_docx: Path,
    bundle_paths: Sequence[Path],
    *,
    merged_bundle_path: Path,
    author: str,
    initials: str,
    report_json: Optional[Path],
    report_md: Optional[Path],
    legacy_copies: Sequence[Path],
    allow_skipped: bool,
    allow_existing_comments: bool,
) -> Dict[str, object]:
    if not input_docx.exists():
        die(f"Input DOCX not found: {input_docx}")
    if has_existing_comments(input_docx) and not allow_existing_comments:
        die(
            "Input DOCX already contains comments; use a clean formatted DOCX "
            "or pass --allow-existing-comments explicitly"
        )
    if not bundle_paths:
        die("At least one issue bundle is required")
    missing = [str(path) for path in bundle_paths if not path.exists()]
    if missing:
        die("Issue bundle(s) not found: " + ", ".join(missing))

    merged = merge_bundles(bundle_paths, target_path=str(input_docx), target_format="docx")
    merged_bundle_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(merged_bundle_path, merged)

    apply_summary = apply_comments(
        input_docx,
        merged_bundle_path,
        output_docx,
        author,
        initials,
        None,
        None,
    )
    applied_count = len(apply_summary.get("applied", []))
    skipped_count = len(apply_summary.get("skipped", []))
    if skipped_count and not allow_skipped:
        die(f"{skipped_count} issue(s) were skipped; refusing to publish editor-facing DOCX")

    word_comment_count = count_word_comments(output_docx)
    if word_comment_count != applied_count:
        die(f"Word comment count mismatch: comments={word_comment_count}, applied={applied_count}")

    copied = copy_if_requested(output_docx, legacy_copies)
    summary: Dict[str, object] = {
        "input_docx": str(input_docx),
        "output_docx": str(output_docx),
        "merged_bundle": str(merged_bundle_path),
        "input_bundles": [str(path) for path in bundle_paths],
        "input_bundle_count": len(bundle_paths),
        "issue_count": len(merged.get("issues", [])),
        "applied": applied_count,
        "skipped": skipped_count,
        "word_comment_count": word_comment_count,
        "legacy_copies": copied,
        "author": author,
        "initials": initials,
    }

    if report_json:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if report_md:
        write_markdown_report(report_md, summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build one all-review DOCX from layered issue bundles")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build")
    build.add_argument("input_docx")
    build.add_argument("output_docx")
    build.add_argument("issue_bundles", nargs="+")
    build.add_argument("--merged-bundle", required=True)
    build.add_argument("--author", default="Automate review")
    build.add_argument("--initials", default="AR")
    build.add_argument("--report-json")
    build.add_argument("--report-md")
    build.add_argument("--legacy-copy", action="append", default=[])
    build.add_argument("--allow-skipped", action="store_true")
    build.add_argument("--allow-existing-comments", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "build":
        parser.error("Unknown command")
        return 2

    summary = build_all_review_docx(
        Path(args.input_docx),
        Path(args.output_docx),
        [Path(item) for item in args.issue_bundles],
        merged_bundle_path=Path(args.merged_bundle),
        author=args.author,
        initials=args.initials,
        report_json=Path(args.report_json) if args.report_json else None,
        report_md=Path(args.report_md) if args.report_md else None,
        legacy_copies=[Path(item) for item in args.legacy_copy],
        allow_skipped=args.allow_skipped,
        allow_existing_comments=args.allow_existing_comments,
    )
    print(
        json.dumps(
            {
                "issues": summary["issue_count"],
                "applied": summary["applied"],
                "skipped": summary["skipped"],
                "word_comments": summary["word_comment_count"],
                "output": summary["output_docx"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
