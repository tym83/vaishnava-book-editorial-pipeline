#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""
Build and merge review issue bundles that can later be applied as:
- Word comments
- PDF annotations
- InDesign notes

Examples:
  python3 review_issue_bundle.py from-comparator cmp.json out.json --target-format docx
  python3 review_issue_bundle.py from-reference-scan refs.json out.json --target-format docx
  python3 review_issue_bundle.py from-style-audit audit.json out.json
  python3 review_issue_bundle.py from-semantic-report semantic.json out.json
  python3 review_issue_bundle.py from-review-report review.json out.json
  python3 review_issue_bundle.py from-footnote-report footnotes.json out.json --docx file.docx
  python3 review_issue_bundle.py merge merged.json a.json b.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from lxml import etree

from review_issue_utils import build_issue, clean_text, empty_bundle, load_json, write_json


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
W = f"{{{W_NS}}}"


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def convert_doc_to_docx(path: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="review-issue-bundle-doc-"))
    subprocess.run(
        [
            "soffice",
            "--headless",
            "--convert-to",
            "docx",
            "--outdir",
            str(temp_dir),
            str(path),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    converted = temp_dir / f"{path.stem}.docx"
    if not converted.exists():
        die(f"Could not convert {path} to docx")
    return converted


def resolve_docx(path: Path) -> Tuple[Path, Optional[Path]]:
    if not path.exists():
        die(f"File not found: {path}")
    if path.suffix.lower() == ".doc":
        converted = convert_doc_to_docx(path)
        return converted, converted.parent
    if path.suffix.lower() != ".docx":
        die("Expected .docx or .doc")
    return path, None


def cleanup_temp(temp_dir: Optional[Path]) -> None:
    if temp_dir and temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)


def paragraph_anchor(paragraph_index: int, part: str = "word/document.xml", story_label: str = "main_story") -> Dict[str, object]:
    return {
        "part": part,
        "paragraph_index": max(1, int(paragraph_index)),
        "story_label": story_label,
    }


def footnote_anchor(footnote_id: int, paragraph_index: int) -> Dict[str, object]:
    return {
        "part": "word/footnotes.xml",
        "paragraph_index": max(1, int(paragraph_index)),
        "footnote_id": int(footnote_id),
    }


def page_anchor(page: int) -> Dict[str, object]:
    return {"page": max(1, int(page))}


def load_footnote_anchor_map(docx_path: Path) -> Dict[int, int]:
    with zipfile.ZipFile(docx_path, "r") as z:
        if "word/footnotes.xml" not in z.namelist():
            return {}
        root = etree.fromstring(z.read("word/footnotes.xml"))

    mapping: Dict[int, int] = {}
    index = 0
    for footnote in root.xpath(".//w:footnote[not(@w:type)]", namespaces=NS):
        footnote_id_raw = footnote.get(f"{W}id")
        if footnote_id_raw is None:
            continue
        try:
            footnote_id = int(footnote_id_raw)
        except ValueError:
            continue
        for p in footnote.xpath(".//w:p", namespaces=NS):
            index += 1
            if footnote_id not in mapping:
                mapping[footnote_id] = index
    return mapping


def message_for_structural_issue(item: Dict[str, object]) -> Tuple[str, str]:
    kind = item.get("kind", "")
    source_excerpt = clean_text(str(item.get("source_excerpt", "")))
    target_excerpt = clean_text(str(item.get("target_excerpt", "")))
    if kind == "struct_delete":
        title = "Возможный пропуск перевода"
        message = (
            "В английском исходнике есть блок, для которого не найден соответствующий русский блок.\n"
            f"Source: {source_excerpt}\n"
            f"Target anchor: {target_excerpt or '<insertion point>'}"
        )
    elif kind == "struct_insert":
        title = "Возможный лишний фрагмент"
        message = (
            "В русском тексте найден блок, которому не соответствует английский исходник.\n"
            f"Target: {target_excerpt}\n"
            f"Nearest source context: {source_excerpt or '<none>'}"
        )
    else:
        title = "Структурное расхождение"
        message = (
            "Структура source и target расходится на этом участке.\n"
            f"Source: {source_excerpt}\n"
            f"Target: {target_excerpt}"
        )
    return title, message


def reference_issue_anchor(item: Dict[str, object], target_format: str, story_label: str) -> Dict[str, object]:
    if target_format == "pdf":
        return page_anchor(1)
    paragraph_index = int(item.get("paragraph_index_in_part") or item.get("block_index") or 1)
    part = str(item.get("block_part") or item.get("part") or "word/document.xml")
    return paragraph_anchor(paragraph_index, part=part, story_label=story_label)


def build_reference_issues(
    reference_scan: Dict[str, object],
    *,
    target_format: str,
    story_label: str,
    issue_prefix: str,
    include_format_issues: bool = True,
) -> List[Dict[str, object]]:
    raw_references = reference_scan.get("references")
    if not isinstance(raw_references, list):
        return []

    issues: List[Dict[str, object]] = []
    unresolved_index = 0
    format_index = 0

    for item in raw_references:
        if not isinstance(item, dict):
            continue

        anchor = reference_issue_anchor(item, target_format=target_format, story_label=story_label)
        normalized_ref = clean_text(str(item.get("normalized_ref", "")))
        raw_text = clean_text(str(item.get("raw_text", "")))
        canonical_display = clean_text(str(item.get("canonical_display") or normalized_ref))
        replacement_text = str(item.get("replacement_text") or canonical_display)
        excerpt = clean_text(str(item.get("block_excerpt", "")))
        web_path = str(item.get("web_path") or "")
        h1 = clean_text(str(item.get("h1", "")))
        metadata = {
            "normalized_ref": normalized_ref,
            "raw_text": raw_text,
            "canonical_display": canonical_display,
            "replacement_text": replacement_text,
            "work_id": item.get("work_id"),
            "web_path": web_path,
            "html_path": item.get("html_path"),
            "block_locator": item.get("block_locator"),
            "block_section": item.get("block_section"),
            "part": item.get("block_part"),
            "paragraph_index_in_part": item.get("paragraph_index_in_part"),
            "container_id": item.get("container_id"),
            "source_locator": item.get("source_locator"),
            "verse_id": item.get("verse_id"),
        }

        if not item.get("resolved"):
            unresolved_index += 1
            message_lines = [
                "Ссылка на шастру распознана, но не резолвится в локальном Vedabase.",
                f"Reference: {normalized_ref or raw_text or '<unknown>'}",
            ]
            if raw_text and raw_text != normalized_ref:
                message_lines.append(f"Raw text: {raw_text}")
            if web_path:
                message_lines.append(f"Expected Vedabase path: {web_path}")
            if excerpt:
                message_lines.append(f"Excerpt: {excerpt}")
            issues.append(
                build_issue(
                    issue_id=f"{issue_prefix}-unresolved-{unresolved_index:04d}",
                    kind="scripture_reference_unresolved",
                    severity="warning",
                    title="Неразрешенная шастрическая ссылка",
                    message="\n".join(message_lines),
                    anchor=anchor,
                    suggestion=(
                        "Проверить формат ссылки, книгу/песнь/главу/стих и наличие нужной страницы "
                        "в локальном зеркале Vedabase."
                    ),
                    context={"excerpt": excerpt},
                    metadata=metadata,
                )
            )
            continue

        if include_format_issues and item.get("needs_normalization"):
            format_index += 1
            message_lines = [
                "Ссылка резолвится, но оформлена неканонически.",
                f"Current: {raw_text or normalized_ref or '<unknown>'}",
                f"Preferred: {replacement_text}",
            ]
            if h1:
                message_lines.append(f"Vedabase page: {h1}")
            elif web_path:
                message_lines.append(f"Vedabase path: {web_path}")
            if excerpt:
                message_lines.append(f"Excerpt: {excerpt}")
            issues.append(
                build_issue(
                    issue_id=f"{issue_prefix}-format-{format_index:04d}",
                    kind="scripture_reference_format",
                    severity="info",
                    title="Нормализовать формат шастрической ссылки",
                    message="\n".join(message_lines),
                    anchor=anchor,
                    suggestion=(
                        "Привести ссылку к каноническому виду вручную или прогнать "
                        "`docx_scripture_reference_normalizer.py`."
                    ),
                    context={"excerpt": excerpt},
                    metadata=metadata,
                )
            )

    return issues


def bundle_from_comparator(report_path: Path, target_format: str, target_path: str, story_label: str) -> Dict[str, object]:
    report = load_json(report_path)
    bundle = empty_bundle(
        target_format=target_format,
        target_path=target_path or str(report.get("target_path", "")),
        source_reports=[str(report_path)],
    )
    issues: List[Dict[str, object]] = []

    for idx, item in enumerate(report.get("issues", []), 1):
        source_range = item.get("source_range") or [0, 0]
        target_range = item.get("target_range") or [0, 0]
        anchor_para = int(target_range[0] or target_range[1] or 1)
        title, message = message_for_structural_issue(item)
        anchor = paragraph_anchor(anchor_para, story_label=story_label)
        if target_format == "pdf":
            anchor = page_anchor(1)
        issues.append(
            build_issue(
                issue_id=f"cmp-struct-{idx:04d}",
                kind=str(item.get("kind", "struct_issue")),
                severity="warning",
                title=title,
                message=message,
                anchor=anchor,
                suggestion="Проверить, есть ли пропуск, лишний фрагмент или ошибочная сегментация.",
                context={
                    "source_excerpt": str(item.get("source_excerpt", "")),
                    "target_excerpt": str(item.get("target_excerpt", "")),
                },
                metadata={
                    "source_range": source_range,
                    "target_range": target_range,
                    "details": item.get("details", {}),
                },
            )
        )

    for idx, item in enumerate(report.get("aligned_suspicious", []), 1):
        anchor_para = int(item.get("target_index") or 1)
        title = "Подозрительное выравнивание source/target"
        message = (
            "Пара блоков выровнена структурно, но отличается по типу, числам или сноскам.\n"
            f"Source: {clean_text(str(item.get('source_excerpt', '')))}\n"
            f"Target: {clean_text(str(item.get('target_excerpt', '')))}"
        )
        anchor = paragraph_anchor(anchor_para, story_label=story_label)
        if target_format == "pdf":
            anchor = page_anchor(1)
        issues.append(
            build_issue(
                issue_id=f"cmp-align-{idx:04d}",
                kind="aligned_suspicious",
                severity="info",
                title=title,
                message=message,
                anchor=anchor,
                suggestion="Сверить смысл, числа, ссылки и тип блока.",
                context={
                    "source_excerpt": str(item.get("source_excerpt", "")),
                    "target_excerpt": str(item.get("target_excerpt", "")),
                },
                metadata={
                    "source_index": item.get("source_index"),
                    "target_index": item.get("target_index"),
                    "source_kind": item.get("source_kind"),
                    "target_kind": item.get("target_kind"),
                    "details": item.get("details", {}),
                },
            )
        )

    reference_scan = report.get("target_reference_scan")
    if isinstance(reference_scan, dict):
        issues.extend(
            build_reference_issues(
                reference_scan,
                target_format=target_format,
                story_label=story_label,
                issue_prefix="cmp-ref",
            )
        )

    bundle["issues"] = issues
    return bundle


def bundle_from_reference_scan(
    report_path: Path,
    target_format: str,
    target_path: str,
    story_label: str,
    *,
    unresolved_only: bool = False,
) -> Dict[str, object]:
    report = load_json(report_path)
    bundle = empty_bundle(
        target_format=target_format,
        target_path=target_path or str(report.get("input_path", "")),
        source_reports=[str(report_path)],
    )
    bundle["issues"] = build_reference_issues(
        report,
        target_format=target_format,
        story_label=story_label,
        issue_prefix="refscan",
        include_format_issues=not unresolved_only,
    )
    return bundle


def bundle_from_style_audit(report_path: Path, target_path: str, story_label: str) -> Dict[str, object]:
    report = load_json(report_path)
    bundle = empty_bundle(target_format="docx", target_path=target_path or str(report.get("file", "")), source_reports=[str(report_path)])
    issues: List[Dict[str, object]] = []
    for idx, item in enumerate(report.get("issues", []), 1):
        excerpt = clean_text(str(item.get("excerpt", "")))
        part = str(item.get("part", "word/document.xml"))
        paragraph_index = int(item.get("paragraph_index") or 1)
        details = item.get("details", {})
        issues.append(
            build_issue(
                issue_id=f"audit-{idx:04d}",
                kind=str(item.get("kind", "style_issue")),
                severity=str(item.get("severity", "warning")),
                title="Замечание по структуре/стилям",
                message=(
                    f"Найдено замечание типа `{item.get('kind', '')}`.\n"
                    f"Excerpt: {excerpt}"
                ),
                anchor=paragraph_anchor(paragraph_index, part=part, story_label=story_label),
                suggestion="Проверить стиль, overrides, ручное форматирование или legacy-символы.",
                context={"excerpt": excerpt},
                metadata={
                    "part": part,
                    "paragraph_index": paragraph_index,
                    "details": details,
                },
            )
        )
    bundle["issues"] = issues
    return bundle


def bundle_from_semantic_report(report_path: Path, target_path: str, story_label: str, include_applied: bool) -> Dict[str, object]:
    report = load_json(report_path)
    bundle = empty_bundle(target_format="docx", target_path=target_path or str(report.get("output", "")), source_reports=[str(report_path)])
    issues: List[Dict[str, object]] = []
    rows = list(report.get("review", []))
    if include_applied:
        rows.extend(report.get("applied", []))
    for idx, item in enumerate(rows, 1):
        paragraph_index = int(item.get("index") or 1)
        text = clean_text(str(item.get("text", "")))
        old_style = item.get("old_style", "")
        new_style = item.get("new_style", "")
        issues.append(
            build_issue(
                issue_id=f"semantic-{idx:04d}",
                kind="semantic_style_review",
                severity="info",
                title="Проверить семантический стиль абзаца",
                message=(
                    f"Абзац требует review по стилю.\n"
                    f"Current style: {old_style}\n"
                    f"Suggested style: {new_style or '<none>'}\n"
                    f"Reason: {item.get('reason', '')}\n"
                    f"Text: {text}"
                ),
                anchor=paragraph_anchor(paragraph_index, story_label=story_label),
                suggestion="Подтвердить или исправить абзацный стиль.",
                context={"excerpt": text},
                metadata={
                    "paragraph_index": paragraph_index,
                    "old_style": old_style,
                    "new_style": new_style,
                    "confidence": item.get("confidence"),
                    "reason": item.get("reason"),
                },
            )
        )
    bundle["issues"] = issues
    return bundle


def bundle_from_review_report(
    report_path: Path,
    target_format: str,
    target_path: str,
) -> Dict[str, object]:
    report = load_json(report_path)
    bundle = empty_bundle(
        target_format=target_format or str(report.get("target_format", "")),
        target_path=target_path or str(report.get("target_path", "")),
        source_reports=[str(report_path)],
    )
    raw_issues = report.get("issues")
    if not isinstance(raw_issues, list):
        bundle["issues"] = []
        return bundle
    bundle["issues"] = [item for item in raw_issues if isinstance(item, dict)]
    return bundle


def bundle_from_footnote_report(report_path: Path, docx_path: Path, target_path: str) -> Dict[str, object]:
    report = load_json(report_path)
    bundle = empty_bundle(target_format="docx", target_path=target_path or str(report.get("output", "")), source_reports=[str(report_path)])
    issues: List[Dict[str, object]] = []
    src, temp_dir = resolve_docx(docx_path)
    try:
        anchor_map = load_footnote_anchor_map(src)
    finally:
        cleanup_temp(temp_dir)

    for idx, item in enumerate(report.get("review", []), 1):
        footnote_id = int(item.get("footnote_id") or 0)
        paragraph_index = anchor_map.get(footnote_id)
        if paragraph_index is None:
            continue
        text = clean_text(str(item.get("text", "")))
        issues.append(
            build_issue(
                issue_id=f"footnote-{idx:04d}",
                kind="footnote_style_review",
                severity="info",
                title="Проверить тип сноски",
                message=(
                    f"Сноска требует review.\n"
                    f"Suggested style: {item.get('new_style', '')}\n"
                    f"Reason: {item.get('reason', '')}\n"
                    f"Text: {text}"
                ),
                anchor=footnote_anchor(footnote_id, paragraph_index),
                suggestion="Подтвердить или исправить стиль сноски.",
                context={"excerpt": text},
                metadata={
                    "footnote_id": footnote_id,
                    "old_styles": item.get("old_styles", []),
                    "new_style": item.get("new_style"),
                    "confidence": item.get("confidence"),
                    "reason": item.get("reason"),
                },
            )
        )
    bundle["issues"] = issues
    return bundle


def merge_bundles(paths: Sequence[Path], target_path: str, target_format: str) -> Dict[str, object]:
    merged = empty_bundle(target_format=target_format, target_path=target_path)
    issues: List[Dict[str, object]] = []
    source_reports: List[str] = []
    for path in paths:
        bundle = load_json(path)
        source_reports.extend(bundle.get("source_reports", []))
        if not merged["target_path"] and bundle.get("target_path"):
            merged["target_path"] = bundle.get("target_path", "")
        if not merged["target_format"] and bundle.get("target_format"):
            merged["target_format"] = bundle.get("target_format", "")
        issues.extend(bundle.get("issues", []))
    merged["source_reports"] = sorted(dict.fromkeys(source_reports))
    merged["issues"] = issues
    return merged


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build issue bundles for comments/annotations/notes")
    sub = parser.add_subparsers(dest="command", required=True)

    p_cmp = sub.add_parser("from-comparator")
    p_cmp.add_argument("report_json")
    p_cmp.add_argument("output_json")
    p_cmp.add_argument("--target-format", default="docx", choices=["docx", "pdf", "indd"])
    p_cmp.add_argument("--target-path", default="")
    p_cmp.add_argument("--story-label", default="main_story")

    p_ref = sub.add_parser("from-reference-scan")
    p_ref.add_argument("report_json")
    p_ref.add_argument("output_json")
    p_ref.add_argument("--target-format", default="docx", choices=["docx", "pdf", "indd"])
    p_ref.add_argument("--target-path", default="")
    p_ref.add_argument("--story-label", default="main_story")
    p_ref.add_argument("--unresolved-only", action="store_true")

    p_audit = sub.add_parser("from-style-audit")
    p_audit.add_argument("report_json")
    p_audit.add_argument("output_json")
    p_audit.add_argument("--target-path", default="")
    p_audit.add_argument("--story-label", default="main_story")

    p_sem = sub.add_parser("from-semantic-report")
    p_sem.add_argument("report_json")
    p_sem.add_argument("output_json")
    p_sem.add_argument("--target-path", default="")
    p_sem.add_argument("--story-label", default="main_story")
    p_sem.add_argument("--include-applied", action="store_true")

    p_review = sub.add_parser("from-review-report")
    p_review.add_argument("report_json")
    p_review.add_argument("output_json")
    p_review.add_argument("--target-format", default="")
    p_review.add_argument("--target-path", default="")

    p_foot = sub.add_parser("from-footnote-report")
    p_foot.add_argument("report_json")
    p_foot.add_argument("output_json")
    p_foot.add_argument("--docx", required=True)
    p_foot.add_argument("--target-path", default="")

    p_merge = sub.add_parser("merge")
    p_merge.add_argument("output_json")
    p_merge.add_argument("inputs", nargs="+")
    p_merge.add_argument("--target-path", default="")
    p_merge.add_argument("--target-format", default="")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "from-comparator":
        bundle = bundle_from_comparator(Path(args.report_json), args.target_format, args.target_path, args.story_label)
    elif args.command == "from-reference-scan":
        bundle = bundle_from_reference_scan(
            Path(args.report_json),
            args.target_format,
            args.target_path,
            args.story_label,
            unresolved_only=args.unresolved_only,
        )
    elif args.command == "from-style-audit":
        bundle = bundle_from_style_audit(Path(args.report_json), args.target_path, args.story_label)
    elif args.command == "from-semantic-report":
        bundle = bundle_from_semantic_report(Path(args.report_json), args.target_path, args.story_label, args.include_applied)
    elif args.command == "from-review-report":
        bundle = bundle_from_review_report(Path(args.report_json), args.target_format, args.target_path)
    elif args.command == "from-footnote-report":
        bundle = bundle_from_footnote_report(Path(args.report_json), Path(args.docx), args.target_path)
    elif args.command == "merge":
        bundle = merge_bundles([Path(x) for x in args.inputs], args.target_path, args.target_format)
    else:
        parser.error("Unknown command")
        return 2

    write_json(Path(getattr(args, "output_json")), bundle)
    print(json.dumps({"issues": len(bundle.get("issues", [])), "output": getattr(args, "output_json")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
