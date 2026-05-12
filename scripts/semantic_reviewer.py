#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Deterministic semantic/theological review queue builder."""

from __future__ import annotations

import argparse
import json
import re
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
from glossary_policy import load_glossary_policy
from review_issue_utils import build_issue
from source_ru_comparator import Block, clean_text, compare_pair, excerpt


SCRIPTURE_REF_EXTRACTOR = re.compile(
    r"(?i)\b(?:"
    r"шб|бг|чч|ав|гв|сдж|шбут|шпу|SB|Bg|Cc|"
    r"adi|madhya|antya"
    r")\s+[\d\.\-,:; ]+"
)
PROTECTED_CATEGORIES = {
    "philosophical_term",
    "scripture_title",
    "honorific",
    "personal_name",
    "place_name",
    "organization",
    "institutional_term",
}
HIGH_IMPACT_KINDS = {
    "heading1",
    "heading2",
    "heading3",
    "heading4",
    "heading_like",
    "shloka",
    "quoted_shloka",
    "shloka_translation",
    "source",
    "source_like",
}


def collect_scripture_refs(text: str) -> List[str]:
    return [clean_text(match.group(0)) for match in SCRIPTURE_REF_EXTRACTOR.finditer(text)]


def contains_phrase(text: str, phrase: str, *, ignore_case: bool = True) -> bool:
    normalized_text = clean_text(text)
    normalized_phrase = clean_text(phrase)
    if not normalized_text or not normalized_phrase:
        return False
    flags = re.IGNORECASE if ignore_case else 0
    pattern = rf"(?<!\w){re.escape(normalized_phrase)}(?!\w)"
    return re.search(pattern, normalized_text, flags=flags) is not None


def dedupe_issues(issues: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
    seen = set()
    out: List[Dict[str, object]] = []
    for item in issues:
        anchor = item.get("anchor") or {}
        key = (
            str(item.get("kind") or ""),
            str(anchor.get("part") or ""),
            int(anchor.get("paragraph_index") or 0),
            clean_text(str(item.get("message") or "")).casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def load_glossary_entries(path: Optional[Path]) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    for entry in load_glossary_policy(path):
        category = clean_text(entry.category).lower()
        approved_form = clean_text(entry.approved_form)
        lemma_en_forms = [clean_text(item) for item in entry.lemma_en_forms if clean_text(item)]
        if category not in PROTECTED_CATEGORIES or not approved_form or not lemma_en_forms:
            continue
        entries.append(
            {
                "category": category,
                "approved_form": approved_form,
                "lemma_en_forms": lemma_en_forms,
            }
        )
    return entries


def build_structural_issues(summary: Dict[str, object], target_blocks: Sequence[Block], story_label: str) -> List[Dict[str, object]]:
    issues: List[Dict[str, object]] = []
    for idx, item in enumerate(summary.get("issues", []), 1):
        target_range = item.get("target_range") or [1, 1]
        target_index = int(target_range[0] or target_range[1] or 1)
        target_index = max(1, min(target_index, len(target_blocks))) if target_blocks else 1
        anchor_block = target_blocks[target_index - 1] if target_blocks else Block(1, "body", "", None, "body", 0, 0, 0, "", False, 0)
        issues.append(
            build_issue(
                issue_id=f"sem-struct-{idx:04d}",
                kind="semantic_structural_review",
                severity="warning",
                title="Проверить смысловую полноту на этом участке",
                message=(
                    "Структура source и target расходится. Это потенциальная смысловая потеря или лишний фрагмент.\n"
                    f"Source: {clean_text(str(item.get('source_excerpt', '')))}\n"
                    f"Target: {clean_text(str(item.get('target_excerpt', '')))}"
                ),
                anchor=paragraph_anchor_for_block(anchor_block, story_label=story_label),
                suggestion="Сверить этот участок по source и проверить, не потерян ли смысл.",
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
    return issues


def build_aligned_issues(summary: Dict[str, object], target_blocks: Sequence[Block], story_label: str) -> List[Dict[str, object]]:
    issues: List[Dict[str, object]] = []
    for idx, item in enumerate(summary.get("aligned_suspicious", []), 1):
        target_index = int(item.get("target_index") or 1)
        target_index = max(1, min(target_index, len(target_blocks))) if target_blocks else 1
        anchor_block = target_blocks[target_index - 1] if target_blocks else Block(1, "body", "", None, "body", 0, 0, 0, "", False, 0)
        details = item.get("details") or {}
        kind = "semantic_aligned_review"
        severity = "info"
        title = "Проверить смысл на выровненном участке"
        suggestion = "Сверить смысл исходного и русского блока."
        if "digit_signature" in details:
            kind = "semantic_number_mismatch"
            severity = "warning"
            title = "Проверить числа и ссылки"
            suggestion = "Сверить цифры, номера стихов, главы, даты и другие числовые данные."
        elif "kind_mismatch" in details:
            kind = "semantic_block_kind_mismatch"
            severity = "warning"
            title = "Проверить тип блока и передачу смысла"
            suggestion = "Проверить, не превратился ли заголовок, шлока, цитата или источник в другой тип блока."
        elif "footnote_refs" in details:
            kind = "semantic_footnote_mismatch"
            severity = "info"
            title = "Проверить сноски на этом участке"
            suggestion = "Проверить, не потерялись ли сноски и не сместились ли ссылки."

        issues.append(
            build_issue(
                issue_id=f"sem-align-{idx:04d}",
                kind=kind,
                severity=severity,
                title=title,
                message=(
                    "Выровненная пара блоков выглядит подозрительно.\n"
                    f"Source: {clean_text(str(item.get('source_excerpt', '')))}\n"
                    f"Target: {clean_text(str(item.get('target_excerpt', '')))}"
                ),
                anchor=paragraph_anchor_for_block(anchor_block, story_label=story_label),
                suggestion=suggestion,
                context={
                    "source_excerpt": str(item.get("source_excerpt", "")),
                    "target_excerpt": str(item.get("target_excerpt", "")),
                },
                metadata={
                    "source_index": item.get("source_index"),
                    "target_index": item.get("target_index"),
                    "source_kind": item.get("source_kind"),
                    "target_kind": item.get("target_kind"),
                    "details": details,
                },
            )
        )
    return issues


def build_reference_issues(summary: Dict[str, object], target_blocks: Sequence[Block], story_label: str) -> List[Dict[str, object]]:
    scan = summary.get("target_reference_scan")
    if not isinstance(scan, dict):
        return []
    issues: List[Dict[str, object]] = []
    for idx, item in enumerate(scan.get("references", []), 1):
        if item.get("resolved"):
            continue
        target_index = int(item.get("block_index") or 1)
        target_index = max(1, min(target_index, len(target_blocks))) if target_blocks else 1
        anchor_block = target_blocks[target_index - 1] if target_blocks else Block(1, "body", "", None, "body", 0, 0, 0, "", False, 0)
        issues.append(
            build_issue(
                issue_id=f"sem-ref-{idx:04d}",
                kind="semantic_scripture_reference_unresolved",
                severity="warning",
                title="Проверить шастрическую ссылку",
                message=(
                    "Ссылка на шастру распознана, но не резолвится в локальном Vedabase.\n"
                    f"Reference: {clean_text(str(item.get('normalized_ref', '')))}\n"
                    f"Excerpt: {clean_text(str(item.get('block_excerpt', '')))}"
                ),
                anchor=paragraph_anchor_for_block(anchor_block, story_label=story_label),
                suggestion="Проверить правильность ссылки и при необходимости открыть место вручную.",
                context={"excerpt": str(item.get("block_excerpt", ""))},
                metadata={
                    "normalized_ref": item.get("normalized_ref"),
                    "raw_text": item.get("raw_text"),
                    "web_path": item.get("web_path"),
                    "block_locator": item.get("block_locator"),
                },
            )
        )
    return issues


def build_extra_alignment_issues(
    source_blocks: Sequence[Block],
    target_blocks: Sequence[Block],
    mapping: Dict[int, int],
    glossary_entries: Sequence[Dict[str, str]],
    story_label: str,
) -> List[Dict[str, object]]:
    issues: List[Dict[str, object]] = []
    issue_index = 0
    for source_index, target_index in sorted(mapping.items()):
        source_block = source_blocks[source_index - 1]
        target_block = target_blocks[target_index - 1]
        source_text = clean_text(source_block.text)
        target_text = clean_text(target_block.text)
        if not source_text or not target_text:
            continue

        source_refs = collect_scripture_refs(source_text)
        target_refs = collect_scripture_refs(target_text)
        if source_refs and source_refs != target_refs:
            issue_index += 1
            issues.append(
                build_issue(
                    issue_id=f"sem-extra-{issue_index:04d}",
                    kind="semantic_reference_mismatch",
                    severity="warning",
                    title="Проверить передачу шастрической ссылки",
                    message=(
                        "В source и target на выровненном участке ссылки выглядят по-разному.\n"
                        f"Source: {source_text}\n"
                        f"Target: {target_text}"
                    ),
                    anchor=paragraph_anchor_for_block(target_block, story_label=story_label),
                    suggestion="Сверить номер книги, главы, стиха и форму ссылки.",
                    context={"source_excerpt": source_text, "target_excerpt": target_text},
                    metadata={"source_index": source_index, "target_index": target_index},
                )
            )

        if source_block.digit_signature and source_block.digit_signature != target_block.digit_signature:
            issue_index += 1
            issues.append(
                build_issue(
                    issue_id=f"sem-extra-{issue_index:04d}",
                    kind="semantic_missing_or_shifted_digits",
                    severity="warning",
                    title="Проверить числа и числовые данные",
                    message=(
                        "Числовые данные в source и target не совпадают.\n"
                        f"Source: {source_text}\n"
                        f"Target: {target_text}"
                    ),
                    anchor=paragraph_anchor_for_block(target_block, story_label=story_label),
                    suggestion="Сверить даты, номера, стихи, ссылки и диапазоны.",
                    context={"source_excerpt": source_text, "target_excerpt": target_text},
                    metadata={
                        "source_index": source_index,
                        "target_index": target_index,
                        "source_digits": source_block.digit_signature,
                        "target_digits": target_block.digit_signature,
                    },
                )
            )

        if source_block.has_quote_marks != target_block.has_quote_marks and (
            source_block.kind in HIGH_IMPACT_KINDS or target_block.kind in HIGH_IMPACT_KINDS
        ):
            issue_index += 1
            issues.append(
                build_issue(
                    issue_id=f"sem-extra-{issue_index:04d}",
                    kind="semantic_quote_or_citation_mismatch",
                    severity="info",
                    title="Проверить цитирование на этом участке",
                    message=(
                        "Source и target по-разному выглядят как цитата/прямая речь.\n"
                        f"Source: {source_text}\n"
                        f"Target: {target_text}"
                    ),
                    anchor=paragraph_anchor_for_block(target_block, story_label=story_label),
                    suggestion="Проверить, не потерялась ли цитата, прямая речь или граница цитирования.",
                    context={"source_excerpt": source_text, "target_excerpt": target_text},
                    metadata={"source_index": source_index, "target_index": target_index},
                )
            )

        if source_block.word_count > 45:
            continue
        for entry in glossary_entries:
            lemma_en_forms = entry["lemma_en_forms"]
            approved_form = entry["approved_form"]
            if not any(contains_phrase(source_text, lemma_en, ignore_case=True) for lemma_en in lemma_en_forms):
                continue
            if contains_phrase(target_text, approved_form, ignore_case=True):
                continue
            issue_index += 1
            severity = "warning" if entry["category"] in {"philosophical_term", "scripture_title", "honorific"} else "info"
            issues.append(
                build_issue(
                    issue_id=f"sem-extra-{issue_index:04d}",
                    kind="semantic_protected_term_review",
                    severity=severity,
                    title="Проверить передачу защищенного термина",
                    message=(
                        "В source встречается термин из защищенной терминосистемы, но его каноническая форма "
                        "не найдена в target.\n"
                        f"Source lemma: {' | '.join(lemma_en_forms)}\n"
                        f"Preferred RU: {approved_form}\n"
                        f"Source: {source_text}\n"
                        f"Target: {target_text}"
                    ),
                    anchor=paragraph_anchor_for_block(target_block, story_label=story_label),
                    suggestion="Проверить, не потерян ли термин и не заменен ли он неточной формой.",
                    context={"source_excerpt": source_text, "target_excerpt": target_text},
                    metadata={
                        "source_index": source_index,
                        "target_index": target_index,
                        "category": entry["category"],
                        "lemma_en_forms": lemma_en_forms,
                        "approved_form": approved_form,
                    },
                )
            )
    return issues


def summarize_kinds(issues: Sequence[Dict[str, object]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in issues:
        kind = str(item.get("kind") or "unknown")
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def review_pair(
    source_path: Path,
    target_path: Path,
    *,
    reference_root: Optional[Path] = None,
    reference_locale: str = "ru",
    glossary_approved: Optional[Path] = None,
    story_label: str = "main_story",
) -> Dict[str, object]:
    summary = compare_pair(
        source_path,
        target_path,
        None,
        None,
        reference_root=reference_root,
        reference_locale=reference_locale,
    )
    resolved_items: List[ResolvedInput] = []
    try:
        source_doc = load_resolved_input(source_path)
        target_doc = load_resolved_input(target_path)
        resolved_items.extend([source_doc, target_doc])
        glossary_entries = load_glossary_entries(glossary_approved)
        mapping = align_structural_blocks(source_doc.blocks, target_doc.blocks)

        issues: List[Dict[str, object]] = []
        issues.extend(build_structural_issues(summary, target_doc.blocks, story_label))
        issues.extend(build_aligned_issues(summary, target_doc.blocks, story_label))
        issues.extend(build_reference_issues(summary, target_doc.blocks, story_label))
        issues.extend(build_extra_alignment_issues(source_doc.blocks, target_doc.blocks, mapping, glossary_entries, story_label))
        issues = dedupe_issues(issues)

        return {
            "version": 1,
            "report_kind": "semantic_review",
            "target_format": target_format_from_path(target_path),
            "target_path": str(target_path),
            "source_path": str(source_path),
            "reference_root": str(reference_root) if reference_root else "",
            "glossary_approved": str(glossary_approved) if glossary_approved else "",
            "summary": {
                "issues": len(issues),
                "source_blocks": len(source_doc.blocks),
                "target_blocks": len(target_doc.blocks),
                "match_ratio": summary.get("match_ratio"),
                "issue_kinds": summarize_kinds(issues),
                "protected_glossary_entries": len(glossary_entries),
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
    source_dir: Path,
    target_dir: Path,
    output_dir: Path,
    *,
    reference_root: Optional[Path] = None,
    reference_locale: str = "ru",
    glossary_approved: Optional[Path] = None,
    story_label: str = "main_story",
    write_bundles: bool = False,
) -> Dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_files = {numbered_stem(path): path for path in list_candidate_files(source_dir) if re.match(r"^\d{3}", path.stem)}
    target_files = {numbered_stem(path): path for path in list_candidate_files(target_dir) if re.match(r"^\d{3}", path.stem)}
    common = sorted(set(source_files) & set(target_files))
    source_only = sorted(set(source_files) - set(target_files))
    target_only = sorted(set(target_files) - set(source_files))
    chapters = []

    for key in common:
        report = review_pair(
            source_files[key],
            target_files[key],
            reference_root=reference_root,
            reference_locale=reference_locale,
            glossary_approved=glossary_approved,
            story_label=story_label,
        )
        json_path = output_dir / f"{key}.json"
        md_path = output_dir / f"{key}.md"
        write_report_json(json_path, report)
        write_report_md(
            md_path,
            title="Semantic Review",
            summary_lines=[
                f"Source: `{source_files[key]}`",
                f"Target: `{target_files[key]}`",
                "",
                f"- issues: {report['summary']['issues']}",
                f"- match_ratio: {report['summary']['match_ratio']}",
                f"- issue_kinds: {report['summary']['issue_kinds']}",
            ],
            issues=report["issues"],
        )
        if write_bundles:
            write_bundle_from_report(output_dir / f"{key}.issues.json", report)
        chapters.append(
            {
                "chapter": key,
                "source": str(source_files[key]),
                "target": str(target_files[key]),
                "issue_count": report["summary"]["issues"],
                "match_ratio": report["summary"]["match_ratio"],
                "issue_kinds": report["summary"]["issue_kinds"],
            }
        )

    index = {
        "version": 1,
        "report_kind": "semantic_review_dir",
        "source_dir": str(source_dir),
        "target_dir": str(target_dir),
        "chapters": chapters,
        "source_only": source_only,
        "target_only": target_only,
    }
    write_report_json(output_dir / "index.json", index)
    write_report_md(
        output_dir / "index.md",
        title="Semantic Review Index",
        summary_lines=[
            f"Source dir: `{source_dir}`",
            f"Target dir: `{target_dir}`",
            "",
            f"- compared: {len(chapters)}",
            f"- source_only: {len(source_only)}",
            f"- target_only: {len(target_only)}",
        ],
        issues=[],
        max_issue_lines=0,
    )
    return index


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a deterministic semantic/theological review queue")
    sub = parser.add_subparsers(dest="command", required=True)

    pair = sub.add_parser("review", help="review one source/target pair")
    pair.add_argument("source")
    pair.add_argument("target")
    pair.add_argument("--reference-root")
    pair.add_argument("--reference-locale", default="ru")
    pair.add_argument("--glossary-approved")
    pair.add_argument("--story-label", default="main_story")
    pair.add_argument("--report-json")
    pair.add_argument("--report-md")
    pair.add_argument("--bundle-json")

    dir_cmd = sub.add_parser("review-dir", help="review numbered chapter directories")
    dir_cmd.add_argument("source_dir")
    dir_cmd.add_argument("target_dir")
    dir_cmd.add_argument("output_dir")
    dir_cmd.add_argument("--reference-root")
    dir_cmd.add_argument("--reference-locale", default="ru")
    dir_cmd.add_argument("--glossary-approved")
    dir_cmd.add_argument("--story-label", default="main_story")
    dir_cmd.add_argument("--write-bundles", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "review":
        report = review_pair(
            Path(args.source),
            Path(args.target),
            reference_root=Path(args.reference_root) if args.reference_root else None,
            reference_locale=args.reference_locale,
            glossary_approved=Path(args.glossary_approved) if args.glossary_approved else None,
            story_label=args.story_label,
        )
        if args.report_json:
            write_report_json(Path(args.report_json), report)
        if args.report_md:
            write_report_md(
                Path(args.report_md),
                title="Semantic Review",
                summary_lines=[
                    f"Source: `{args.source}`",
                    f"Target: `{args.target}`",
                    "",
                    f"- issues: {report['summary']['issues']}",
                    f"- match_ratio: {report['summary']['match_ratio']}",
                    f"- issue_kinds: {report['summary']['issue_kinds']}",
                ],
                issues=report["issues"],
            )
        if args.bundle_json:
            write_bundle_from_report(Path(args.bundle_json), report)
        write_json_stdout(report)
        return 0

    if args.command == "review-dir":
        index = review_dirs(
            Path(args.source_dir),
            Path(args.target_dir),
            Path(args.output_dir),
            reference_root=Path(args.reference_root) if args.reference_root else None,
            reference_locale=args.reference_locale,
            glossary_approved=Path(args.glossary_approved) if args.glossary_approved else None,
            story_label=args.story_label,
            write_bundles=args.write_bundles,
        )
        write_json_stdout(index)
        return 0

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
