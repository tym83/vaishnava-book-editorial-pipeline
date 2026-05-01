#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Find update candidates in old RU using new EN and optional old EN."""

from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from editorial_review_common import (
    ResolvedInput,
    align_structural_blocks,
    cleanup_resolved_inputs,
    load_resolved_input,
    paragraph_anchor_for_block,
    target_format_from_path,
    write_bundle_from_report,
    write_json_stdout,
    write_report_json,
    write_report_md,
)
from review_issue_utils import build_issue
from source_ru_comparator import Block, clean_text, compare_pair, excerpt


SCRIPTURE_REF_EXTRACTOR = re.compile(
    r"(?i)\b(?:"
    r"шб|бг|чч|ав|гв|сдж|шбут|шпу|SB|Bg|Cc|"
    r"adi|madhya|antya"
    r")\s+[\d\.\-,:; ]+"
)

HIGH_IMPACT_KINDS = {
    "heading1",
    "heading2",
    "heading3",
    "heading4",
    "heading_like",
    "shloka",
    "shloka_translation",
    "quoted_shloka",
    "source",
    "source_like",
}


def block_text_key(block: Block) -> str:
    text = clean_text(block.text).casefold()
    text = re.sub(r"\s+", " ", text)
    return f"{block.kind}|{text}"


def blocks_excerpt(blocks: Sequence[Block], start: int, end: int, limit: int = 240) -> str:
    if start < 1 or end < 1 or start > len(blocks):
        return ""
    joined = " ".join(clean_text(blocks[idx - 1].text) for idx in range(start, min(end, len(blocks)) + 1))
    return excerpt(joined, limit=limit)


def collect_text(blocks: Sequence[Block], start: int, end: int) -> str:
    if start < 1 or end < 1 or start > len(blocks):
        return ""
    return " ".join(clean_text(blocks[idx - 1].text) for idx in range(start, min(end, len(blocks)) + 1)).strip()


def collect_kinds(blocks: Sequence[Block], start: int, end: int) -> List[str]:
    if start < 1 or end < 1:
        return []
    return [blocks[idx - 1].kind for idx in range(start, min(end, len(blocks)) + 1)]


def collect_digits(text: str) -> List[str]:
    return re.findall(r"\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?", text)


def collect_scripture_refs(text: str) -> List[str]:
    return [clean_text(match.group(0)) for match in SCRIPTURE_REF_EXTRACTOR.finditer(text)]


def project_source_range_to_target(
    source_start: int,
    source_end: int,
    mapping: Dict[int, int],
    target_total: int,
) -> Tuple[int, int]:
    positions = [mapping[idx] for idx in range(source_start, source_end + 1) if idx in mapping]
    if positions:
        return max(1, min(positions)), max(1, min(target_total, max(positions)))

    before = [mapping[idx] for idx in mapping if idx < source_start]
    after = [mapping[idx] for idx in mapping if idx > source_end]
    if before and after:
        anchor = max(1, min(target_total, before[-1] + 1))
        if anchor > after[0]:
            anchor = max(1, min(target_total, after[0]))
        return anchor, anchor
    if before:
        anchor = max(1, min(target_total, before[-1]))
        return anchor, anchor
    if after:
        anchor = max(1, min(target_total, after[0]))
        return anchor, anchor
    return 1, max(1, min(target_total, 1))


def classify_change(
    old_en_blocks: Sequence[Block],
    new_en_blocks: Sequence[Block],
    old_start: int,
    old_end: int,
    new_start: int,
    new_end: int,
) -> Dict[str, object]:
    old_text = collect_text(old_en_blocks, old_start, old_end)
    new_text = collect_text(new_en_blocks, new_start, new_end)
    ratio = SequenceMatcher(a=old_text.casefold(), b=new_text.casefold(), autojunk=False).ratio() if old_text or new_text else 1.0
    old_digits = collect_digits(old_text)
    new_digits = collect_digits(new_text)
    old_refs = collect_scripture_refs(old_text)
    new_refs = collect_scripture_refs(new_text)
    old_kinds = collect_kinds(old_en_blocks, old_start, old_end)
    new_kinds = collect_kinds(new_en_blocks, new_start, new_end)
    combined_kinds = set(old_kinds) | set(new_kinds)
    word_delta = abs(len(old_text.split()) - len(new_text.split()))

    flags: List[str] = []
    if old_digits != new_digits:
        flags.append("digits_changed")
    if old_refs != new_refs:
        flags.append("scripture_refs_changed")
    if combined_kinds & HIGH_IMPACT_KINDS:
        flags.append("high_impact_block_kind")
    if (old_end - old_start) != (new_end - new_start):
        flags.append("block_span_changed")
    if ratio < 0.92:
        flags.append("substantial_text_change")
    if word_delta >= 8:
        flags.append("word_count_shift")

    meaningful = bool(flags) and (
        "digits_changed" in flags
        or "scripture_refs_changed" in flags
        or "high_impact_block_kind" in flags
        or "substantial_text_change" in flags
        or "word_count_shift" in flags
    )
    if not meaningful and ratio < 0.97:
        meaningful = True

    priority = "low"
    severity = "info"
    if "digits_changed" in flags or "scripture_refs_changed" in flags or "high_impact_block_kind" in flags:
        priority = "high"
        severity = "warning"
    elif meaningful:
        priority = "medium"
        severity = "warning"

    return {
        "old_text": old_text,
        "new_text": new_text,
        "ratio": ratio,
        "word_delta": word_delta,
        "old_digits": old_digits,
        "new_digits": new_digits,
        "old_refs": old_refs,
        "new_refs": new_refs,
        "old_kinds": old_kinds,
        "new_kinds": new_kinds,
        "flags": flags,
        "meaningful": meaningful,
        "priority": priority,
        "severity": severity,
    }


def build_update_issues(
    *,
    old_en: ResolvedInput,
    new_en: ResolvedInput,
    old_ru: ResolvedInput,
    include_minor: bool,
    story_label: str,
) -> List[Dict[str, object]]:
    alignment = align_structural_blocks(old_en.blocks, old_ru.blocks)
    matcher = SequenceMatcher(
        a=[block_text_key(block) for block in old_en.blocks],
        b=[block_text_key(block) for block in new_en.blocks],
        autojunk=False,
    )
    issues: List[Dict[str, object]] = []

    for idx, (tag, i1, i2, j1, j2) in enumerate(matcher.get_opcodes(), 1):
        if tag == "equal":
            continue

        old_start = i1 + 1 if i2 > i1 else max(1, i1)
        old_end = i2 if i2 > i1 else max(1, i1)
        new_start = j1 + 1 if j2 > j1 else max(1, j1)
        new_end = j2 if j2 > j1 else max(1, j1)
        change = classify_change(old_en.blocks, new_en.blocks, old_start, old_end, new_start, new_end)
        if not include_minor and not change["meaningful"]:
            continue

        anchor_start, anchor_end = project_source_range_to_target(old_start, old_end, alignment, len(old_ru.blocks))
        anchor_block = old_ru.blocks[max(0, min(anchor_start, len(old_ru.blocks)) - 1)]
        old_ru_excerpt = blocks_excerpt(old_ru.blocks, anchor_start, anchor_end)
        old_en_excerpt = blocks_excerpt(old_en.blocks, old_start, old_end)
        new_en_excerpt = blocks_excerpt(new_en.blocks, new_start, new_end)

        message_lines = [
            "Новый английский текст отличается от старой английской версии на этом участке.",
            f"Old EN: {old_en_excerpt or '<none>'}",
            f"New EN: {new_en_excerpt or '<none>'}",
        ]
        if old_ru_excerpt:
            message_lines.append(f"Current RU: {old_ru_excerpt}")
        if change["flags"]:
            message_lines.append(f"Signals: {', '.join(change['flags'])}")

        issues.append(
            build_issue(
                issue_id=f"update-{idx:04d}",
                kind="old_ru_new_en_update_candidate",
                severity=str(change["severity"]),
                title="Проверить RU по новой EN редакции",
                message="\n".join(message_lines),
                anchor=paragraph_anchor_for_block(anchor_block, story_label=story_label),
                suggestion="Сверить старый RU с новым EN и при необходимости переперевести этот фрагмент.",
                context={
                    "source_excerpt": old_en_excerpt,
                    "target_excerpt": old_ru_excerpt,
                    "excerpt": new_en_excerpt,
                },
                metadata={
                    "change_tag": tag,
                    "priority": change["priority"],
                    "meaningful": change["meaningful"],
                    "change_ratio": round(float(change["ratio"]), 4),
                    "word_delta": int(change["word_delta"]),
                    "change_flags": list(change["flags"]),
                    "old_en_range": [old_start, old_end],
                    "new_en_range": [new_start, new_end],
                    "old_ru_anchor_range": [anchor_start, anchor_end],
                    "old_digits": list(change["old_digits"]),
                    "new_digits": list(change["new_digits"]),
                    "old_refs": list(change["old_refs"]),
                    "new_refs": list(change["new_refs"]),
                },
            )
        )
    return issues


def build_degraded_issues(
    *,
    new_en_path: Path,
    old_ru_path: Path,
    story_label: str,
) -> List[Dict[str, object]]:
    summary = compare_pair(new_en_path, old_ru_path, None, None)
    issues: List[Dict[str, object]] = []

    for idx, item in enumerate(summary.get("issues", []), 1):
        target_range = item.get("target_range") or [1, 1]
        anchor_para = int(target_range[0] or target_range[1] or 1)
        issues.append(
            build_issue(
                issue_id=f"update-degraded-struct-{idx:04d}",
                kind="old_ru_new_en_structural_review",
                severity="warning",
                title="Проверить RU по новому EN без old EN",
                message=(
                    "Работа идет в деградированном режиме без старого английского текста.\n"
                    f"Source: {clean_text(str(item.get('source_excerpt', '')))}\n"
                    f"Target: {clean_text(str(item.get('target_excerpt', '')))}"
                ),
                anchor={"part": "word/document.xml", "paragraph_index": anchor_para, "story_label": story_label},
                suggestion="Сравнить текущий RU с новым EN вручную: здесь есть структурное расхождение.",
                context={
                    "source_excerpt": str(item.get("source_excerpt", "")),
                    "target_excerpt": str(item.get("target_excerpt", "")),
                },
                metadata={
                    "source_range": item.get("source_range"),
                    "target_range": item.get("target_range"),
                    "details": item.get("details"),
                },
            )
        )

    for idx, item in enumerate(summary.get("aligned_suspicious", []), 1):
        target_index = int(item.get("target_index") or 1)
        issues.append(
            build_issue(
                issue_id=f"update-degraded-align-{idx:04d}",
                kind="old_ru_new_en_aligned_review",
                severity="info",
                title="Подозрительное место для обновления RU",
                message=(
                    "Без old EN найден участок, который структурно выровнен, но выглядит подозрительно.\n"
                    f"Source: {clean_text(str(item.get('source_excerpt', '')))}\n"
                    f"Target: {clean_text(str(item.get('target_excerpt', '')))}"
                ),
                anchor={"part": "word/document.xml", "paragraph_index": target_index, "story_label": story_label},
                suggestion="Проверить смысл, числа, тип блока и полноту перевода.",
                context={
                    "source_excerpt": str(item.get("source_excerpt", "")),
                    "target_excerpt": str(item.get("target_excerpt", "")),
                },
                metadata={
                    "source_index": item.get("source_index"),
                    "target_index": item.get("target_index"),
                    "source_kind": item.get("source_kind"),
                    "target_kind": item.get("target_kind"),
                    "details": item.get("details"),
                },
            )
        )
    return issues


def summarize_priorities(issues: Sequence[Dict[str, object]]) -> Dict[str, int]:
    counts = {"high": 0, "medium": 0, "low": 0}
    for item in issues:
        priority = str((item.get("metadata") or {}).get("priority") or "low")
        if priority not in counts:
            priority = "low"
        counts[priority] += 1
    return counts


def review_pair(
    old_ru_path: Path,
    new_en_path: Path,
    *,
    old_en_path: Optional[Path] = None,
    story_label: str = "main_story",
    include_minor: bool = False,
) -> Dict[str, object]:
    resolved_items: List[ResolvedInput] = []
    try:
        old_ru = load_resolved_input(old_ru_path)
        new_en = load_resolved_input(new_en_path)
        resolved_items.extend([old_ru, new_en])

        if old_en_path is not None:
            old_en = load_resolved_input(old_en_path)
            resolved_items.append(old_en)
            mode = "with_old_en"
            issues = build_update_issues(
                old_en=old_en,
                new_en=new_en,
                old_ru=old_ru,
                include_minor=include_minor,
                story_label=story_label,
            )
        else:
            mode = "degraded_no_old_en"
            issues = build_degraded_issues(
                new_en_path=new_en_path,
                old_ru_path=old_ru_path,
                story_label=story_label,
            )

        meaningful = sum(1 for item in issues if (item.get("metadata") or {}).get("meaningful", True))
        priorities = summarize_priorities(issues)
        return {
            "version": 1,
            "report_kind": "old_ru_new_en_update_helper",
            "mode": mode,
            "target_format": target_format_from_path(old_ru_path),
            "target_path": str(old_ru_path),
            "old_ru_path": str(old_ru_path),
            "new_en_path": str(new_en_path),
            "old_en_path": str(old_en_path) if old_en_path else "",
            "summary": {
                "issues": len(issues),
                "meaningful": meaningful,
                "priorities": priorities,
                "old_ru_blocks": len(old_ru.blocks),
                "new_en_blocks": len(new_en.blocks),
                "old_en_blocks": len(old_en.blocks) if old_en_path is not None else 0,
            },
            "issues": issues,
        }
    finally:
        cleanup_resolved_inputs(resolved_items)


def numbered_stem(path: Path) -> str:
    match = re.match(r"^(\d{3})", path.stem)
    return match.group(1) if match else path.stem


def list_candidate_files(path: Path) -> List[Path]:
    return [
        item
        for item in sorted(path.iterdir())
        if item.is_file() and item.suffix.lower() in {".doc", ".docx", ".pdf", ".txt", ".md", ".json"}
    ]


def review_dirs(
    old_ru_dir: Path,
    new_en_dir: Path,
    output_dir: Path,
    *,
    old_en_dir: Optional[Path] = None,
    story_label: str = "main_story",
    include_minor: bool = False,
    write_bundles: bool = False,
) -> Dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    old_ru_files = {numbered_stem(path): path for path in list_candidate_files(old_ru_dir)}
    new_en_files = {numbered_stem(path): path for path in list_candidate_files(new_en_dir)}
    old_en_files = {numbered_stem(path): path for path in list_candidate_files(old_en_dir)} if old_en_dir else {}

    common = sorted(set(old_ru_files) & set(new_en_files))
    old_ru_only = sorted(set(old_ru_files) - set(new_en_files))
    new_en_only = sorted(set(new_en_files) - set(old_ru_files))
    old_en_missing = sorted(key for key in common if old_en_dir and key not in old_en_files)
    chapters = []

    for key in common:
        report = review_pair(
            old_ru_files[key],
            new_en_files[key],
            old_en_path=old_en_files.get(key) if old_en_dir else None,
            story_label=story_label,
            include_minor=include_minor,
        )
        json_path = output_dir / f"{key}.json"
        md_path = output_dir / f"{key}.md"
        write_report_json(json_path, report)
        write_report_md(
            md_path,
            title="Old RU vs New EN Update Helper",
            summary_lines=[
                f"Old RU: `{old_ru_files[key]}`",
                f"New EN: `{new_en_files[key]}`",
                f"Old EN: `{old_en_files.get(key, '') if old_en_dir else ''}`",
                "",
                f"- mode: {report['mode']}",
                f"- issues: {report['summary']['issues']}",
                f"- meaningful: {report['summary']['meaningful']}",
                f"- priorities: {report['summary']['priorities']}",
            ],
            issues=report["issues"],
        )
        if write_bundles:
            write_bundle_from_report(output_dir / f"{key}.issues.json", report)
        chapters.append(
            {
                "chapter": key,
                "old_ru": str(old_ru_files[key]),
                "new_en": str(new_en_files[key]),
                "old_en": str(old_en_files.get(key, "")),
                "mode": report["mode"],
                "issue_count": report["summary"]["issues"],
                "meaningful_count": report["summary"]["meaningful"],
                "priorities": report["summary"]["priorities"],
            }
        )

    index = {
        "version": 1,
        "report_kind": "old_ru_new_en_update_helper_dir",
        "old_ru_dir": str(old_ru_dir),
        "new_en_dir": str(new_en_dir),
        "old_en_dir": str(old_en_dir) if old_en_dir else "",
        "chapters": chapters,
        "old_ru_only": old_ru_only,
        "new_en_only": new_en_only,
        "old_en_missing": old_en_missing,
    }
    write_report_json(output_dir / "index.json", index)
    lines = [
        f"Old RU dir: `{old_ru_dir}`",
        f"New EN dir: `{new_en_dir}`",
        f"Old EN dir: `{old_en_dir}`" if old_en_dir else "Old EN dir: `<none>`",
        "",
        f"- compared: {len(chapters)}",
        f"- old_ru_only: {len(old_ru_only)}",
        f"- new_en_only: {len(new_en_only)}",
        f"- old_en_missing: {len(old_en_missing)}",
    ]
    if old_ru_only:
        lines.append(f"- old_ru_only_keys: {', '.join(old_ru_only)}")
    if new_en_only:
        lines.append(f"- new_en_only_keys: {', '.join(new_en_only)}")
    if old_en_missing:
        lines.append(f"- old_en_missing_keys: {', '.join(old_en_missing)}")
    write_report_md(
        output_dir / "index.md",
        title="Old RU vs New EN Update Helper Index",
        summary_lines=lines,
        issues=[],
        max_issue_lines=0,
    )
    return index


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Find old RU segments that likely need updates from new EN")
    sub = parser.add_subparsers(dest="command", required=True)

    pair = sub.add_parser("compare", help="review one old-RU/new-EN pair")
    pair.add_argument("old_ru")
    pair.add_argument("new_en")
    pair.add_argument("--old-en")
    pair.add_argument("--report-json")
    pair.add_argument("--report-md")
    pair.add_argument("--bundle-json")
    pair.add_argument("--story-label", default="main_story")
    pair.add_argument("--include-minor", action="store_true")

    dir_cmd = sub.add_parser("compare-dir", help="review numbered chapter directories")
    dir_cmd.add_argument("old_ru_dir")
    dir_cmd.add_argument("new_en_dir")
    dir_cmd.add_argument("output_dir")
    dir_cmd.add_argument("--old-en-dir")
    dir_cmd.add_argument("--story-label", default="main_story")
    dir_cmd.add_argument("--include-minor", action="store_true")
    dir_cmd.add_argument("--write-bundles", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "compare":
        report = review_pair(
            Path(args.old_ru),
            Path(args.new_en),
            old_en_path=Path(args.old_en) if args.old_en else None,
            story_label=args.story_label,
            include_minor=args.include_minor,
        )
        if args.report_json:
            write_report_json(Path(args.report_json), report)
        if args.report_md:
            write_report_md(
                Path(args.report_md),
                title="Old RU vs New EN Update Helper",
                summary_lines=[
                    f"Old RU: `{args.old_ru}`",
                    f"New EN: `{args.new_en}`",
                    f"Old EN: `{args.old_en or ''}`",
                    "",
                    f"- mode: {report['mode']}",
                    f"- issues: {report['summary']['issues']}",
                    f"- meaningful: {report['summary']['meaningful']}",
                    f"- priorities: {report['summary']['priorities']}",
                ],
                issues=report["issues"],
            )
        if args.bundle_json:
            write_bundle_from_report(Path(args.bundle_json), report)
        write_json_stdout(report)
        return 0

    if args.command == "compare-dir":
        index = review_dirs(
            Path(args.old_ru_dir),
            Path(args.new_en_dir),
            Path(args.output_dir),
            old_en_dir=Path(args.old_en_dir) if args.old_en_dir else None,
            story_label=args.story_label,
            include_minor=args.include_minor,
            write_bundles=args.write_bundles,
        )
        write_json_stdout(index)
        return 0

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
