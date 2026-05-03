#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Deterministic Russian stylistic/proofreading review queue builder."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from editorial_review_common import (
    ResolvedInput,
    cleanup_resolved_inputs,
    load_resolved_input,
    paragraph_anchor_for_block,
    target_format_from_path,
    write_bundle_from_report,
    write_json_stdout,
    write_report_json,
    write_report_md,
)
from glossary_policy import contains_phrase, load_glossary_policy
from review_issue_utils import build_issue
from source_ru_comparator import Block, clean_text


DOUBLE_SPACE_RE = re.compile(r"[ \t]{2,}")
SPACE_BEFORE_PUNCT_RE = re.compile(r"[ \t\u00a0]+([,;:.!?»)\]])")
MISSING_SPACE_AFTER_PUNCT_RE = re.compile(r"([,;:!?])(?![\s»\"\'])(?=[А-Яа-яЁёA-Za-z])")
STRAIGHT_QUOTES_RE = re.compile(r'"')
LATIN_CYRILLIC_MIX_RE = re.compile(r"(?i)(?<=[А-Яа-яЁё])[A-Za-z](?=[А-Яа-яЁё])|(?<=[A-Za-z])[А-Яа-яЁё](?=[A-Za-z])")
DIGIT_INSIDE_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]+\d+[А-Яа-яЁё]+")
ASCII_DASH_RE = re.compile(r"\s-\s")
TRIPLE_DOTS_RE = re.compile(r"\.\.\.")
REPEATED_PUNCT_RE = re.compile(r"([!?;,])\1+|,{2,}|;;+|::+")
LONG_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")
PROSE_TERMINAL_PUNCT_RE = re.compile(r"[.!?…»\"]\s*$")


def issue_from_block(
    block: Block,
    *,
    issue_id: str,
    kind: str,
    severity: str,
    title: str,
    message: str,
    suggestion: str,
    story_label: str,
    metadata: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    return build_issue(
        issue_id=issue_id,
        kind=kind,
        severity=severity,
        title=title,
        message=message,
        anchor=paragraph_anchor_for_block(block, story_label=story_label),
        suggestion=suggestion,
        context={"excerpt": clean_text(block.text)},
        metadata=metadata or {"paragraph_index": block.index, "part": block.part, "style_name": block.style_name, "block_kind": block.kind},
    )


def analyze_block(block: Block, story_label: str, issue_counter: List[int]) -> List[Dict[str, object]]:
    text = block.text or ""
    normalized = clean_text(text)
    issues: List[Dict[str, object]] = []
    if not normalized:
        return issues

    def next_id() -> str:
        issue_counter[0] += 1
        return f"sty-{issue_counter[0]:04d}"

    if DOUBLE_SPACE_RE.search(text):
        issues.append(
            issue_from_block(
                block,
                issue_id=next_id(),
                kind="stylistic_double_spaces",
                severity="info",
                title="Убрать лишние пробелы",
                message="В абзаце есть повторяющиеся пробелы или табы.",
                suggestion="Нормализовать межсловные пробелы.",
                story_label=story_label,
            )
        )
    if SPACE_BEFORE_PUNCT_RE.search(text):
        issues.append(
            issue_from_block(
                block,
                issue_id=next_id(),
                kind="stylistic_space_before_punctuation",
                severity="warning",
                title="Лишний пробел перед знаком препинания",
                message="Перед знаком препинания есть лишний пробел.",
                suggestion="Убрать пробел перед знаком препинания.",
                story_label=story_label,
            )
        )
    if MISSING_SPACE_AFTER_PUNCT_RE.search(text):
        issues.append(
            issue_from_block(
                block,
                issue_id=next_id(),
                kind="stylistic_missing_space_after_punctuation",
                severity="warning",
                title="Проверить пробел после знака препинания",
                message="После знака препинания, вероятно, пропущен пробел.",
                suggestion="Проверить расстановку пробелов после запятой, двоеточия или другого знака.",
                story_label=story_label,
            )
        )
    if STRAIGHT_QUOTES_RE.search(text):
        issues.append(
            issue_from_block(
                block,
                issue_id=next_id(),
                kind="stylistic_straight_quotes",
                severity="info",
                title="Заменить прямые кавычки",
                message='В абзаце используются прямые кавычки `"`.',
                suggestion="Проверить и заменить на типографские кавычки там, где это нужно.",
                story_label=story_label,
            )
        )
    if text.count("«") != text.count("»"):
        issues.append(
            issue_from_block(
                block,
                issue_id=next_id(),
                kind="stylistic_unbalanced_quotes",
                severity="warning",
                title="Проверить парность кавычек",
                message="Количество открывающих и закрывающих русских кавычек не совпадает.",
                suggestion="Проверить границы цитаты и вложенные кавычки.",
                story_label=story_label,
            )
        )
    if LATIN_CYRILLIC_MIX_RE.search(text):
        issues.append(
            issue_from_block(
                block,
                issue_id=next_id(),
                kind="stylistic_latin_cyrillic_mix",
                severity="warning",
                title="Смешение латиницы и кириллицы",
                message="Внутри слова смешаны латинские и кириллические буквы.",
                suggestion="Проверить OCR-ошибки и заменить неправильные символы.",
                story_label=story_label,
            )
        )
    if DIGIT_INSIDE_CYRILLIC_RE.search(text):
        issues.append(
            issue_from_block(
                block,
                issue_id=next_id(),
                kind="stylistic_digit_inside_cyrillic_word",
                severity="warning",
                title="Цифра внутри кириллического слова",
                message="Внутри кириллического слова встретилась цифра, что похоже на OCR-ошибку.",
                suggestion="Проверить написание слова и заменить цифру на букву, если это ошибка.",
                story_label=story_label,
            )
        )
    if ASCII_DASH_RE.search(text):
        issues.append(
            issue_from_block(
                block,
                issue_id=next_id(),
                kind="stylistic_ascii_dash_with_spaces",
                severity="info",
                title="Проверить тире",
                message="Между словами используется ASCII-дефис с пробелами.",
                suggestion="Проверить, не нужен ли здесь типографский тире.",
                story_label=story_label,
            )
        )
    if TRIPLE_DOTS_RE.search(text):
        issues.append(
            issue_from_block(
                block,
                issue_id=next_id(),
                kind="stylistic_three_dots",
                severity="info",
                title="Проверить многоточие",
                message="Вместо символа многоточия используются три точки.",
                suggestion="Заменить `...` на `…`, если это соответствует вашей типографике.",
                story_label=story_label,
            )
        )
    if REPEATED_PUNCT_RE.search(text):
        issues.append(
            issue_from_block(
                block,
                issue_id=next_id(),
                kind="stylistic_repeated_punctuation",
                severity="warning",
                title="Повторяющиеся знаки препинания",
                message="В абзаце есть подозрительные повторы знаков препинания.",
                suggestion="Проверить пунктуацию на этом участке.",
                story_label=story_label,
            )
        )
    if text.count("(") != text.count(")"):
        issues.append(
            issue_from_block(
                block,
                issue_id=next_id(),
                kind="stylistic_unbalanced_parentheses",
                severity="warning",
                title="Проверить скобки",
                message="Количество открывающих и закрывающих скобок не совпадает.",
                suggestion="Проверить парность скобок и границы вставки.",
                story_label=story_label,
            )
        )

    if block.kind == "body":
        sentences = [chunk for chunk in LONG_SENTENCE_SPLIT_RE.split(normalized) if chunk]
        long_sentences = [item for item in sentences if len(item.split()) >= 45]
        if long_sentences:
            issues.append(
                issue_from_block(
                    block,
                    issue_id=next_id(),
                    kind="stylistic_long_sentence_review",
                    severity="info",
                    title="Проверить длинную фразу",
                    message="В абзаце есть очень длинное предложение, которое может требовать литературной редактуры.",
                    suggestion="Проверить читаемость и при необходимости упростить синтаксис без потери смысла.",
                    story_label=story_label,
                    metadata={
                        "paragraph_index": block.index,
                        "part": block.part,
                        "style_name": block.style_name,
                        "block_kind": block.kind,
                        "long_sentence_count": len(long_sentences),
                    },
                )
            )
        if block.translit_score >= 3:
            issues.append(
                issue_from_block(
                    block,
                    issue_id=next_id(),
                    kind="stylistic_diacritics_in_prose",
                    severity="info",
                    title="Проверить диакритику в прозе",
                    message="В прозаическом абзаце есть выраженная санскритская диакритика.",
                    suggestion="Проверить, должна ли диакритика сохраняться в этом месте или ее нужно снять.",
                    story_label=story_label,
                )
            )
        if block.word_count >= 14 and not PROSE_TERMINAL_PUNCT_RE.search(normalized):
            issues.append(
                issue_from_block(
                    block,
                    issue_id=next_id(),
                    kind="stylistic_missing_terminal_punctuation",
                    severity="info",
                    title="Проверить конец абзаца",
                    message="Длинный прозаический абзац не заканчивается ожидаемым знаком препинания.",
                    suggestion="Проверить, не потерялась ли точка или другой завершающий знак.",
                    story_label=story_label,
                )
            )

    return issues


def build_glossary_policy_issues(
    blocks: Sequence[Block],
    *,
    glossary_approved: Optional[Path],
    story_label: str,
    issue_counter: List[int],
) -> List[Dict[str, object]]:
    glossary_entries = load_glossary_policy(glossary_approved)
    if not glossary_entries:
        return []

    issues: List[Dict[str, object]] = []

    def next_id() -> str:
        issue_counter[0] += 1
        return f"sty-{issue_counter[0]:04d}"

    for block in blocks:
        normalized = clean_text(block.text or "")
        if not normalized:
            continue
        for entry in glossary_entries:
            if not entry.discouraged_forms:
                continue
            for discouraged_form in entry.discouraged_forms:
                if not contains_phrase(normalized, discouraged_form, ignore_case=False):
                    continue
                issues.append(
                    issue_from_block(
                        block,
                        issue_id=next_id(),
                        kind="stylistic_glossary_discouraged_form",
                        severity="warning",
                        title="Проверить неканоническую словарную форму",
                        message=(
                            "В тексте найдена форма, которую ручной BBT-backed glossary помечает "
                            "как нежелательную.\n"
                            f"Found: {discouraged_form}\n"
                            f"Preferred: {entry.approved_form}"
                        ),
                        suggestion="Сверить написание с glossary policy и заменить на каноническую форму, если это не особый случай.",
                        story_label=story_label,
                        metadata={
                            "approved_form": entry.approved_form,
                            "discouraged_form": discouraged_form,
                            "glossary_entry_id": entry.entry_id,
                            "category": entry.category,
                        },
                    )
                )
    return issues


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


def summarize_kinds(issues: Sequence[Dict[str, object]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in issues:
        kind = str(item.get("kind") or "unknown")
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def review_file(
    target_path: Path,
    *,
    story_label: str = "main_story",
    glossary_approved: Optional[Path] = None,
) -> Dict[str, object]:
    resolved_items: List[ResolvedInput] = []
    try:
        target_doc = load_resolved_input(target_path)
        resolved_items.append(target_doc)
        counter = [0]
        issues: List[Dict[str, object]] = []
        for block in target_doc.blocks:
            issues.extend(analyze_block(block, story_label, counter))
        issues.extend(
            build_glossary_policy_issues(
                target_doc.blocks,
                glossary_approved=glossary_approved,
                story_label=story_label,
                issue_counter=counter,
            )
        )
        issues = dedupe_issues(issues)
        return {
            "version": 1,
            "report_kind": "stylistic_review",
            "target_format": target_format_from_path(target_path),
            "target_path": str(target_path),
            "summary": {
                "issues": len(issues),
                "target_blocks": len(target_doc.blocks),
                "issue_kinds": summarize_kinds(issues),
                "glossary_policy_entries": len(load_glossary_policy(glossary_approved)),
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


def review_dir(
    target_dir: Path,
    output_dir: Path,
    *,
    story_label: str = "main_story",
    glossary_approved: Optional[Path] = None,
    write_bundles: bool = False,
) -> Dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    target_files = {numbered_stem(path): path for path in list_candidate_files(target_dir)}
    chapters = []
    for key in sorted(target_files):
        report = review_file(target_files[key], story_label=story_label, glossary_approved=glossary_approved)
        write_report_json(output_dir / f"{key}.json", report)
        write_report_md(
            output_dir / f"{key}.md",
            title="Stylistic Review",
            summary_lines=[
                f"Target: `{target_files[key]}`",
                "",
                f"- issues: {report['summary']['issues']}",
                f"- issue_kinds: {report['summary']['issue_kinds']}",
                f"- glossary_policy_entries: {report['summary']['glossary_policy_entries']}",
            ],
            issues=report["issues"],
        )
        if write_bundles:
            write_bundle_from_report(output_dir / f"{key}.issues.json", report)
        chapters.append(
            {
                "chapter": key,
                "target": str(target_files[key]),
                "issue_count": report["summary"]["issues"],
                "issue_kinds": report["summary"]["issue_kinds"],
            }
        )
    index = {
        "version": 1,
        "report_kind": "stylistic_review_dir",
        "target_dir": str(target_dir),
        "chapters": chapters,
    }
    write_report_json(output_dir / "index.json", index)
    write_report_md(
        output_dir / "index.md",
        title="Stylistic Review Index",
        summary_lines=[
            f"Target dir: `{target_dir}`",
            "",
            f"- compared: {len(chapters)}",
        ],
        issues=[],
        max_issue_lines=0,
    )
    return index


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a deterministic Russian stylistic review queue")
    sub = parser.add_subparsers(dest="command", required=True)

    review = sub.add_parser("review", help="review one target file")
    review.add_argument("target")
    review.add_argument("--story-label", default="main_story")
    review.add_argument("--glossary-approved")
    review.add_argument("--report-json")
    review.add_argument("--report-md")
    review.add_argument("--bundle-json")

    review_dir_cmd = sub.add_parser("review-dir", help="review a numbered chapter directory")
    review_dir_cmd.add_argument("target_dir")
    review_dir_cmd.add_argument("output_dir")
    review_dir_cmd.add_argument("--story-label", default="main_story")
    review_dir_cmd.add_argument("--glossary-approved")
    review_dir_cmd.add_argument("--write-bundles", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "review":
        report = review_file(
            Path(args.target),
            story_label=args.story_label,
            glossary_approved=Path(args.glossary_approved) if args.glossary_approved else None,
        )
        if args.report_json:
            write_report_json(Path(args.report_json), report)
        if args.report_md:
            write_report_md(
                Path(args.report_md),
                title="Stylistic Review",
                summary_lines=[
                    f"Target: `{args.target}`",
                    "",
                    f"- issues: {report['summary']['issues']}",
                    f"- issue_kinds: {report['summary']['issue_kinds']}",
                    f"- glossary_policy_entries: {report['summary']['glossary_policy_entries']}",
                ],
                issues=report["issues"],
            )
        if args.bundle_json:
            write_bundle_from_report(Path(args.bundle_json), report)
        write_json_stdout(report)
        return 0

    if args.command == "review-dir":
        index = review_dir(
            Path(args.target_dir),
            Path(args.output_dir),
            story_label=args.story_label,
            glossary_approved=Path(args.glossary_approved) if args.glossary_approved else None,
            write_bundles=args.write_bundles,
        )
        write_json_stdout(index)
        return 0

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
