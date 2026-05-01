#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for editorial review reports and issue bundles."""

from __future__ import annotations

import json
from difflib import SequenceMatcher
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from review_issue_utils import empty_bundle, write_json
from source_ru_comparator import Block, block_signature, cleanup_temp, extract_blocks, resolve_source


@dataclass
class ResolvedInput:
    original_path: Path
    resolved_path: Path
    source_format: str
    temp_dir: Optional[Path]
    blocks: List[Block]


def load_resolved_input(path: Path) -> ResolvedInput:
    resolved_path, source_format, temp_dir = resolve_source(path)
    blocks = extract_blocks(resolved_path, source_format)
    return ResolvedInput(
        original_path=path,
        resolved_path=resolved_path,
        source_format=source_format,
        temp_dir=temp_dir,
        blocks=blocks,
    )


def cleanup_resolved_inputs(items: Iterable[ResolvedInput]) -> None:
    for item in items:
        cleanup_temp(item.temp_dir)


def paragraph_anchor_for_block(block: Block, story_label: str = "main_story") -> Dict[str, object]:
    part = str(block.part or "word/document.xml")
    if part == "body":
        part = "word/document.xml"
    return {
        "part": part,
        "paragraph_index": max(1, int(block.index or 1)),
        "story_label": story_label,
    }


def target_format_from_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".doc", ".docx"}:
        return "docx"
    if suffix == ".pdf":
        return "pdf"
    return "text"


def align_structural_blocks(source_blocks: Sequence[Block], target_blocks: Sequence[Block]) -> Dict[int, int]:
    matcher = SequenceMatcher(
        a=[block_signature(block) for block in source_blocks],
        b=[block_signature(block) for block in target_blocks],
        autojunk=False,
    )
    mapping: Dict[int, int] = {}
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            continue
        length = min(i2 - i1, j2 - j1)
        for offset in range(length):
            mapping[i1 + offset + 1] = j1 + offset + 1
    return mapping


def build_bundle_from_report(
    report: Dict[str, object],
    *,
    target_path: Optional[str] = None,
    target_format: Optional[str] = None,
) -> Dict[str, object]:
    effective_target_path = target_path or str(report.get("target_path") or report.get("input_path") or "")
    effective_target_format = target_format or str(report.get("target_format") or "")
    if not effective_target_format and effective_target_path:
        effective_target_format = target_format_from_path(Path(effective_target_path))
    bundle = empty_bundle(
        target_format=effective_target_format,
        target_path=effective_target_path,
        source_reports=[str(report.get("report_path") or "")] if report.get("report_path") else [],
    )
    raw_issues = report.get("issues")
    if isinstance(raw_issues, list):
        bundle["issues"] = [item for item in raw_issues if isinstance(item, dict)]
    else:
        bundle["issues"] = []
    return bundle


def write_bundle_from_report(
    output_path: Path,
    report: Dict[str, object],
    *,
    target_path: Optional[str] = None,
    target_format: Optional[str] = None,
) -> Dict[str, object]:
    bundle = build_bundle_from_report(
        report,
        target_path=target_path,
        target_format=target_format,
    )
    write_json(output_path, bundle)
    return bundle


def issue_markdown_lines(issues: Sequence[Dict[str, object]], *, limit: int = 200) -> List[str]:
    lines: List[str] = []
    shown = 0
    for item in issues:
        if shown >= limit:
            break
        shown += 1
        title = str(item.get("title") or item.get("kind") or "Issue")
        lines.append(f"- `{item.get('severity', 'warning')}` {title}\n")
        message = str(item.get("message") or "").strip()
        if message:
            for line in message.splitlines():
                lines.append(f"  - {line}\n")
        context = item.get("context") or {}
        excerpt = str(context.get("excerpt") or context.get("target_excerpt") or context.get("source_excerpt") or "").strip()
        if excerpt:
            lines.append(f"  - excerpt: `{excerpt}`\n")
    hidden = len(issues) - shown
    if hidden > 0:
        lines.append(f"- ... {hidden} more issues omitted\n")
    return lines


def write_report_json(path: Path, report: Dict[str, object]) -> None:
    payload = dict(report)
    payload["report_path"] = str(path)
    write_json(path, payload)


def write_report_md(
    path: Path,
    *,
    title: str,
    summary_lines: Sequence[str],
    issues: Sequence[Dict[str, object]],
    max_issue_lines: int = 200,
) -> None:
    lines: List[str] = [f"# {title}\n\n"]
    for line in summary_lines:
        normalized = line.rstrip()
        if normalized:
            lines.append(f"{normalized}\n")
        else:
            lines.append("\n")
    lines.append("\n## Issues\n\n")
    lines.append(f"- count: {len(issues)}\n")
    lines.extend(issue_markdown_lines(issues, limit=max_issue_lines))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")


def write_json_stdout(payload: Dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
