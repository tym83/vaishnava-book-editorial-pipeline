#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


ISSUE_BUNDLE_VERSION = 1


def clean_text(text: str) -> str:
    return " ".join((text or "").replace("\u00a0", " ").strip().split())


def excerpt(text: str, limit: int = 180) -> str:
    text = clean_text(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def normalize_severity(value: Optional[str]) -> str:
    allowed = {"info", "warning", "error", "critical"}
    severity = (value or "warning").strip().lower()
    return severity if severity in allowed else "warning"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_issue(
    issue_id: str,
    kind: str,
    severity: str,
    title: str,
    message: str,
    anchor: Optional[Dict[str, Any]] = None,
    suggestion: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "id": issue_id,
        "kind": kind,
        "severity": normalize_severity(severity),
        "title": title,
        "message": message.strip(),
        "suggestion": suggestion.strip() if suggestion else "",
        "anchor": anchor or {},
        "context": context or {},
        "metadata": metadata or {},
    }


def issue_body(issue: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"[{issue.get('severity', 'warning').upper()}] {issue.get('title', '').strip()}")
    if issue.get("kind"):
        lines.append(f"Kind: {issue['kind']}")
    message = issue.get("message", "").strip()
    if message:
        lines.append("")
        lines.append(message)

    suggestion = issue.get("suggestion", "").strip()
    if suggestion:
        lines.append("")
        lines.append("Suggested action:")
        lines.append(suggestion)

    context = issue.get("context") or {}
    if context:
        lines.append("")
        lines.append("Context:")
        for key in ("excerpt", "source_excerpt", "target_excerpt"):
            value = clean_text(str(context.get(key, "")))
            if value:
                lines.append(f"- {key}: {value}")

    metadata = issue.get("metadata") or {}
    compact_meta = {}
    for key in (
        "source_range",
        "target_range",
        "details",
        "source_kind",
        "target_kind",
        "normalized_ref",
        "raw_text",
        "canonical_display",
        "replacement_text",
        "work_id",
        "web_path",
        "html_path",
        "block_locator",
        "block_section",
        "part",
        "paragraph_index",
        "paragraph_index_in_part",
        "container_id",
        "source_locator",
        "verse_id",
        "footnote_id",
        "page",
    ):
        if key in metadata and metadata[key] not in ("", None, [], {}):
            compact_meta[key] = metadata[key]
    if compact_meta:
        lines.append("")
        lines.append("Metadata:")
        for key, value in compact_meta.items():
            lines.append(f"- {key}: {value}")
    return "\n".join(lines).strip()


def empty_bundle(target_format: str = "", target_path: str = "", source_reports: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "version": ISSUE_BUNDLE_VERSION,
        "target_format": target_format,
        "target_path": target_path,
        "source_reports": source_reports or [],
        "issues": [],
    }
