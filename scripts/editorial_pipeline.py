#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Run the chapter-level editorial pipeline over a book or chapter directories."""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from chapter_splitter import (
    DEFAULT_HEADING_STYLES,
    DEFAULT_TOC_MARKERS,
    convert_doc_to_docx as split_convert_doc_to_docx,
    split_docx,
)
from docx_comment_applier import apply_comments
from docx_scripture_reference_normalizer import cleanup_temp as scripture_cleanup_temp
from docx_scripture_reference_normalizer import process_docx as normalize_scripture_refs_docx
from docx_scripture_reference_normalizer import resolve_docx as scripture_resolve_docx
from docx_style_audit import audit_docx, resolve_source as audit_resolve_source, cleanup_temp as audit_cleanup_temp, write_markdown_report as write_style_audit_md
from docx_style_normalizer import cleanup_temp as style_cleanup_temp
from docx_style_normalizer import normalize_docx as normalize_styles_docx
from docx_style_normalizer import resolve_source as style_resolve_source
from editorial_review_common import target_format_from_path, write_bundle_from_report, write_json_stdout
from old_ru_vs_new_en_update_helper import review_pair as update_review_pair
from review_issue_bundle import bundle_from_comparator, bundle_from_style_audit, merge_bundles
from review_issue_utils import write_json
from semantic_reviewer import review_pair as semantic_review_pair
from source_ru_comparator import compare_pair
from stylistic_reviewer import review_file as stylistic_review_file
from unicode_normalizer import cleanup_temp as unicode_cleanup_temp
from unicode_normalizer import normalize_docx as normalize_unicode_docx
from unicode_normalizer import resolve_source as unicode_resolve_source


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


@dataclass
class PipelineOptions:
    reference_root: Optional[Path]
    reference_locale: str
    glossary_approved: Optional[Path]
    old_en_dir: Optional[Path]
    run_update_without_old_en: bool
    normalize_unicode: bool
    normalize_styles: bool
    normalize_scripture_refs: bool
    apply_comments: bool
    comment_author: str
    comment_initials: str
    story_label: str
    extra_bundle_dirs: List[Path]
    split_mode: str
    heading_styles: List[str]
    toc_markers: List[str]
    title_list: Optional[List[str]]
    max_title_len: int


def numbered_stem(path: Path) -> str:
    stem = path.stem
    if len(stem) >= 3 and stem[:3].isdigit():
        return stem[:3]
    return stem


def list_candidate_files(path: Path) -> List[Path]:
    return [
        item
        for item in sorted(path.iterdir())
        if item.is_file() and item.suffix.lower() in {".doc", ".docx", ".pdf", ".txt", ".md", ".json"}
    ]


def ensure_chapter_dir(
    input_path: Path,
    output_dir: Path,
    *,
    split_mode: str,
    heading_styles: Sequence[str],
    title_list: Optional[Sequence[str]],
    toc_markers: Sequence[str],
    max_title_len: int,
) -> Path:
    if input_path.is_dir():
        return input_path
    suffix = input_path.suffix.lower()
    if suffix not in {".doc", ".docx"}:
        die(f"run-book currently supports .doc/.docx books for splitting, got: {input_path}")
    resolved_docx = input_path
    temp_dir: Optional[Path] = None
    if suffix == ".doc":
        resolved_docx = split_convert_doc_to_docx(input_path)
        temp_dir = resolved_docx.parent
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        split_docx(
            resolved_docx,
            output_dir,
            mode=split_mode,
            heading_styles=heading_styles,
            title_list=title_list,
            toc_markers=toc_markers,
            max_len=max_title_len,
        )
        return output_dir
    finally:
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def load_title_list(path: Optional[str]) -> Optional[List[str]]:
    if not path:
        return None
    title_path = Path(path)
    lines = [line.strip() for line in title_path.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line]


def prepare_target_file(path: Path, output_dir: Path, options: PipelineOptions) -> Dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    current_path = path
    steps: List[Dict[str, object]] = []

    def register_step(name: str, output_path: Path, summary: Dict[str, object]) -> None:
        nonlocal current_path
        steps.append({"step": name, "input": str(current_path), "output": str(output_path), "summary": summary})
        current_path = output_path

    if options.normalize_unicode:
        src, temp_dir = unicode_resolve_source(current_path)
        try:
            out = output_dir / f"{path.stem}.unicode.docx"
            summary = normalize_unicode_docx(src, out, source_font="Gaura Times", target_font="Charis SIL")
            register_step("unicode_normalizer", out, summary)
        finally:
            unicode_cleanup_temp(temp_dir)

    if options.normalize_styles:
        src, temp_dir = style_resolve_source(current_path)
        try:
            out = output_dir / f"{path.stem}.styles.docx"
            summary = normalize_styles_docx(src, out, toc_markers=options.toc_markers, extra_maps=[])
            register_step("docx_style_normalizer", out, summary)
        finally:
            style_cleanup_temp(temp_dir)

    if options.normalize_scripture_refs:
        src, temp_dir = scripture_resolve_docx(current_path)
        try:
            out = output_dir / f"{path.stem}.refs.docx"
            summary = normalize_scripture_refs_docx(src, out)
            register_step("docx_scripture_reference_normalizer", out, summary)
        finally:
            scripture_cleanup_temp(temp_dir)

    return {
        "original": str(path),
        "prepared": str(current_path),
        "steps": steps,
    }


def extra_bundle_paths_for_key(extra_bundle_dirs: Sequence[Path], key: str) -> List[Path]:
    out: List[Path] = []
    for directory in extra_bundle_dirs:
        for candidate_name in (f"{key}.json", f"{key}.issues.json"):
            candidate = directory / candidate_name
            if candidate.exists():
                out.append(candidate)
                break
    return out


def write_markdown_index(path: Path, title: str, lines: Sequence[str]) -> None:
    content = [f"# {title}\n\n"]
    for line in lines:
        content.append(f"{line.rstrip()}\n")
    path.write_text("".join(content), encoding="utf-8")


def run_chapter(
    key: str,
    source_path: Path,
    target_path: Path,
    output_dir: Path,
    options: PipelineOptions,
) -> Dict[str, object]:
    report_dirs = {
        "prepared": output_dir / "prepared",
        "compare": output_dir / "compare",
        "semantic": output_dir / "semantic",
        "stylistic": output_dir / "stylistic",
        "style_audit": output_dir / "style_audit",
        "update": output_dir / "update",
        "issues": output_dir / "issues",
        "commented": output_dir / "commented",
    }
    for directory in report_dirs.values():
        directory.mkdir(parents=True, exist_ok=True)

    prepared_summary = prepare_target_file(target_path, report_dirs["prepared"] / key, options)
    prepared_target = Path(prepared_summary["prepared"])

    compare_summary = compare_pair(
        source_path,
        prepared_target,
        report_dirs["compare"] / f"{key}.md",
        report_dirs["compare"] / f"{key}.json",
        reference_root=options.reference_root,
        reference_locale=options.reference_locale,
    )
    compare_bundle = bundle_from_comparator(
        report_dirs["compare"] / f"{key}.json",
        target_format_from_path(prepared_target),
        str(prepared_target),
        options.story_label,
    )
    write_json(report_dirs["issues"] / f"{key}.compare.json", compare_bundle)

    semantic_report = semantic_review_pair(
        source_path,
        prepared_target,
        reference_root=options.reference_root,
        reference_locale=options.reference_locale,
        glossary_approved=options.glossary_approved,
        story_label=options.story_label,
    )
    semantic_json = report_dirs["semantic"] / f"{key}.json"
    write_json(semantic_json, semantic_report)
    write_markdown_index(
        report_dirs["semantic"] / f"{key}.md",
        "Semantic Review",
        [
            f"Source: `{source_path}`",
            f"Target: `{prepared_target}`",
            "",
            f"- issues: {semantic_report['summary']['issues']}",
            f"- match_ratio: {semantic_report['summary']['match_ratio']}",
            f"- issue_kinds: {semantic_report['summary']['issue_kinds']}",
        ],
    )
    write_bundle_from_report(report_dirs["issues"] / f"{key}.semantic.json", semantic_report)

    stylistic_report = stylistic_review_file(
        prepared_target,
        story_label=options.story_label,
        glossary_approved=options.glossary_approved,
    )
    stylistic_json = report_dirs["stylistic"] / f"{key}.json"
    write_json(stylistic_json, stylistic_report)
    write_markdown_index(
        report_dirs["stylistic"] / f"{key}.md",
        "Stylistic Review",
        [
            f"Target: `{prepared_target}`",
            "",
            f"- issues: {stylistic_report['summary']['issues']}",
            f"- issue_kinds: {stylistic_report['summary']['issue_kinds']}",
        ],
    )
    write_bundle_from_report(report_dirs["issues"] / f"{key}.stylistic.json", stylistic_report)

    style_audit_report = None
    style_audit_bundle_path = None
    if prepared_target.suffix.lower() in {".doc", ".docx"}:
        audit_src, audit_temp_dir = audit_resolve_source(prepared_target)
        try:
            style_audit_report = audit_docx(audit_src, glossary_approved=options.glossary_approved)
        finally:
            audit_cleanup_temp(audit_temp_dir)
        style_audit_json = report_dirs["style_audit"] / f"{key}.json"
        write_json(style_audit_json, style_audit_report)
        write_style_audit_md(style_audit_report, report_dirs["style_audit"] / f"{key}.md")
        style_audit_bundle = bundle_from_style_audit(style_audit_json, str(prepared_target), options.story_label)
        style_audit_bundle_path = report_dirs["issues"] / f"{key}.style_audit.json"
        write_json(style_audit_bundle_path, style_audit_bundle)

    update_bundle_path = None
    if options.old_en_dir is not None or options.run_update_without_old_en:
        old_en_path = None
        if options.old_en_dir is not None:
            candidates = {numbered_stem(item): item for item in list_candidate_files(options.old_en_dir)}
            old_en_path = candidates.get(key)
        if old_en_path is not None or options.run_update_without_old_en:
            update_report = update_review_pair(
                prepared_target,
                source_path,
                old_en_path=old_en_path,
                story_label=options.story_label,
                include_minor=False,
            )
            update_json = report_dirs["update"] / f"{key}.json"
            write_json(update_json, update_report)
            write_markdown_index(
                report_dirs["update"] / f"{key}.md",
                "Old RU vs New EN Update Helper",
                [
                    f"Old RU: `{prepared_target}`",
                    f"New EN: `{source_path}`",
                    f"Old EN: `{old_en_path}`" if old_en_path else "Old EN: `<none>`",
                    "",
                    f"- mode: {update_report['mode']}",
                    f"- issues: {update_report['summary']['issues']}",
                    f"- meaningful: {update_report['summary']['meaningful']}",
                ],
            )
            update_bundle_path = report_dirs["issues"] / f"{key}.update.json"
            write_bundle_from_report(update_bundle_path, update_report)

    bundle_paths = [
        report_dirs["issues"] / f"{key}.compare.json",
        report_dirs["issues"] / f"{key}.semantic.json",
        report_dirs["issues"] / f"{key}.stylistic.json",
    ]
    if style_audit_bundle_path is not None:
        bundle_paths.append(style_audit_bundle_path)
    if update_bundle_path is not None:
        bundle_paths.append(update_bundle_path)
    bundle_paths.extend(extra_bundle_paths_for_key(options.extra_bundle_dirs, key))

    merged_bundle = merge_bundles(bundle_paths, str(prepared_target), target_format_from_path(prepared_target))
    merged_bundle_path = report_dirs["issues"] / f"{key}.merged.json"
    write_json(merged_bundle_path, merged_bundle)

    comment_summary = None
    if options.apply_comments and prepared_target.suffix.lower() in {".doc", ".docx"}:
        commented_output = report_dirs["commented"] / f"{key}.docx"
        comment_summary = apply_comments(
            prepared_target,
            merged_bundle_path,
            commented_output,
            options.comment_author,
            options.comment_initials,
            report_dirs["commented"] / f"{key}.report.json",
            report_dirs["commented"] / f"{key}.report.md",
        )

    return {
        "chapter": key,
        "source": str(source_path),
        "target": str(target_path),
        "prepared_target": str(prepared_target),
        "prepare_steps": prepared_summary["steps"],
        "compare_issue_count": len(compare_summary.get("issues", [])) + len(compare_summary.get("aligned_suspicious", [])),
        "semantic_issue_count": semantic_report["summary"]["issues"],
        "stylistic_issue_count": stylistic_report["summary"]["issues"],
        "style_audit_issue_count": len(style_audit_report.get("issues", [])) if isinstance(style_audit_report, dict) else 0,
        "update_issue_count": len(json.loads(update_bundle_path.read_text(encoding="utf-8")).get("issues", [])) if update_bundle_path and update_bundle_path.exists() else 0,
        "merged_issue_count": len(merged_bundle.get("issues", [])),
        "comments_applied": len((comment_summary or {}).get("applied", [])) if comment_summary else 0,
        "comments_skipped": len((comment_summary or {}).get("skipped", [])) if comment_summary else 0,
        "merged_bundle": str(merged_bundle_path),
    }


def run_dir_pipeline(source_dir: Path, target_dir: Path, output_dir: Path, options: PipelineOptions) -> Dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_files = {numbered_stem(path): path for path in list_candidate_files(source_dir)}
    target_files = {numbered_stem(path): path for path in list_candidate_files(target_dir)}
    common = sorted(set(source_files) & set(target_files))
    source_only = sorted(set(source_files) - set(target_files))
    target_only = sorted(set(target_files) - set(source_files))

    chapters = [run_chapter(key, source_files[key], target_files[key], output_dir, options) for key in common]
    index = {
        "version": 1,
        "report_kind": "editorial_pipeline_dir",
        "source_dir": str(source_dir),
        "target_dir": str(target_dir),
        "old_en_dir": str(options.old_en_dir) if options.old_en_dir else "",
        "chapters": chapters,
        "source_only": source_only,
        "target_only": target_only,
    }
    write_json(output_dir / "index.json", index)
    write_markdown_index(
        output_dir / "index.md",
        "Editorial Pipeline Index",
        [
            f"Source dir: `{source_dir}`",
            f"Target dir: `{target_dir}`",
            f"Old EN dir: `{options.old_en_dir}`" if options.old_en_dir else "Old EN dir: `<none>`",
            "",
            f"- compared: {len(chapters)}",
            f"- source_only: {len(source_only)}",
            f"- target_only: {len(target_only)}",
            f"- total_merged_issues: {sum(item['merged_issue_count'] for item in chapters)}",
            f"- total_comments_applied: {sum(item['comments_applied'] for item in chapters)}",
        ],
    )
    return index


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the editorial pipeline over chapter directories or whole books")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common_options(cmd) -> None:
        cmd.add_argument("--reference-root")
        cmd.add_argument("--reference-locale", default="ru")
        cmd.add_argument("--glossary-approved")
        cmd.add_argument("--old-en-dir")
        cmd.add_argument("--run-update-without-old-en", action="store_true")
        cmd.add_argument("--normalize-unicode", action="store_true")
        cmd.add_argument("--normalize-styles", action="store_true")
        cmd.add_argument("--normalize-scripture-refs", action="store_true")
        cmd.add_argument("--apply-comments", action="store_true")
        cmd.add_argument("--comment-author", default="Sluj editorial")
        cmd.add_argument("--comment-initials", default="SL")
        cmd.add_argument("--story-label", default="main_story")
        cmd.add_argument("--extra-bundle-dir", action="append", default=[])

    run_dir = sub.add_parser("run-dir", help="run the pipeline on numbered chapter directories")
    run_dir.add_argument("source_dir")
    run_dir.add_argument("target_dir")
    run_dir.add_argument("output_dir")
    add_common_options(run_dir)

    run_book = sub.add_parser("run-book", help="split books into chapters if needed, then run the pipeline")
    run_book.add_argument("source_input")
    run_book.add_argument("target_input")
    run_book.add_argument("output_dir")
    run_book.add_argument("--old-en-input")
    run_book.add_argument("--split-mode", choices=["style", "toc", "title-list"], default="style")
    run_book.add_argument("--heading-style", action="append", default=list(DEFAULT_HEADING_STYLES))
    run_book.add_argument("--toc-marker", action="append", default=list(DEFAULT_TOC_MARKERS))
    run_book.add_argument("--title-list")
    run_book.add_argument("--max-title-len", type=int, default=120)
    add_common_options(run_book)
    return parser


def options_from_args(args) -> PipelineOptions:
    return PipelineOptions(
        reference_root=Path(args.reference_root) if args.reference_root else None,
        reference_locale=args.reference_locale,
        glossary_approved=Path(args.glossary_approved) if args.glossary_approved else None,
        old_en_dir=Path(args.old_en_dir) if getattr(args, "old_en_dir", None) else None,
        run_update_without_old_en=bool(getattr(args, "run_update_without_old_en", False)),
        normalize_unicode=bool(getattr(args, "normalize_unicode", False)),
        normalize_styles=bool(getattr(args, "normalize_styles", False)),
        normalize_scripture_refs=bool(getattr(args, "normalize_scripture_refs", False)),
        apply_comments=bool(getattr(args, "apply_comments", False)),
        comment_author=args.comment_author,
        comment_initials=args.comment_initials,
        story_label=args.story_label,
        extra_bundle_dirs=[Path(item) for item in getattr(args, "extra_bundle_dir", [])],
        split_mode=getattr(args, "split_mode", "style"),
        heading_styles=list(getattr(args, "heading_style", list(DEFAULT_HEADING_STYLES))),
        toc_markers=list(getattr(args, "toc_marker", list(DEFAULT_TOC_MARKERS))),
        title_list=load_title_list(getattr(args, "title_list", None)),
        max_title_len=int(getattr(args, "max_title_len", 120)),
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    options = options_from_args(args)

    if args.command == "run-dir":
        index = run_dir_pipeline(Path(args.source_dir), Path(args.target_dir), Path(args.output_dir), options)
        write_json_stdout(index)
        return 0

    if args.command == "run-book":
        output_dir = Path(args.output_dir)
        ingest_dir = output_dir / "ingest"
        source_dir = ensure_chapter_dir(
            Path(args.source_input),
            ingest_dir / "source",
            split_mode=options.split_mode,
            heading_styles=options.heading_styles,
            title_list=options.title_list,
            toc_markers=options.toc_markers,
            max_title_len=options.max_title_len,
        )
        target_dir = ensure_chapter_dir(
            Path(args.target_input),
            ingest_dir / "target",
            split_mode=options.split_mode,
            heading_styles=options.heading_styles,
            title_list=options.title_list,
            toc_markers=options.toc_markers,
            max_title_len=options.max_title_len,
        )
        if args.old_en_input:
            options.old_en_dir = ensure_chapter_dir(
                Path(args.old_en_input),
                ingest_dir / "old_en",
                split_mode=options.split_mode,
                heading_styles=options.heading_styles,
                title_list=options.title_list,
                toc_markers=options.toc_markers,
                max_title_len=options.max_title_len,
            )
        index = run_dir_pipeline(source_dir, target_dir, output_dir, options)
        write_json_stdout(index)
        return 0

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
