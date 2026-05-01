#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Build a structural manifest for the local Vedabase mirror."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from text_structure import (
    find_vedabase_root,
    first_xpath_text,
    list_vedabase_verse_page_paths,
    load_html_tree,
    normalize_vedabase_web_path,
    parse_vedabase_path,
    vedabase_html_path_from_web_path,
)


PAGE_TYPES = ["library_index", "work", "subwork", "chapter", "verse", "advanced_view", "other"]


def iter_index_paths(root: Path) -> Iterable[Path]:
    return sorted(path for path in root.rglob("index.html") if path.is_file())


def extract_links(doc) -> List[str]:
    hrefs = []
    for raw in doc.xpath("//*[@href]/@href"):
        href = str(raw or "").strip()
        if not href.startswith("/"):
            continue
        normalized = normalize_vedabase_web_path(href)
        if normalized:
            hrefs.append(normalized)
    return hrefs


def summarize_page(path: Path, vedabase_root: Path) -> Dict[str, object]:
    raw, doc = load_html_tree(path)
    info = parse_vedabase_path(path)
    title = first_xpath_text(doc, "//title[1]")
    h1 = first_xpath_text(doc, "//h1[1]")
    lang = first_xpath_text(doc, "/html/@lang")
    hrefs = extract_links(doc)

    has_advanced_view_link = False
    has_advanced_view_file = False
    verse_link_count = 0
    verse_child_count = 0
    assembly_mode: Optional[str] = None

    if info.page_type == "chapter":
        if info.advanced_view_web_path:
            has_advanced_view_link = info.advanced_view_web_path in hrefs
            has_advanced_view_file = vedabase_html_path_from_web_path(vedabase_root, info.advanced_view_web_path).exists()
        verse_link_count = sum(
            1
            for href in hrefs
            if parse_vedabase_path(href).page_type == "verse" and parse_vedabase_path(href).chapter_web_path == info.web_path
        )
        verse_child_count = len(list_vedabase_verse_page_paths(path.parent))
        if has_advanced_view_file:
            assembly_mode = "advanced_view"
        elif verse_child_count:
            assembly_mode = "verse_pages"

    return {
        "source_path": str(path),
        "web_path": info.web_path,
        "locale": info.locale,
        "lang": lang,
        "title": title,
        "h1": h1,
        "root_id": info.root_id,
        "work_id": info.work_id,
        "page_type": info.page_type,
        "path_depth": info.path_depth,
        "chapter_number": info.chapter_number,
        "chapter_key": info.chapter_key,
        "chapter_web_path": info.chapter_web_path,
        "advanced_view_web_path": info.advanced_view_web_path,
        "verse_id": info.verse_id,
        "has_advanced_view_link": has_advanced_view_link,
        "has_advanced_view_file": has_advanced_view_file,
        "verse_link_count": verse_link_count,
        "verse_child_count": verse_child_count,
        "assembly_mode": assembly_mode,
        "page_info": info.to_dict(),
    }


def build_manifest(root: Path, page_types: Optional[set[str]] = None, limit: Optional[int] = None) -> Dict[str, object]:
    vedabase_root = find_vedabase_root(root)
    if vedabase_root is None:
        raise SystemExit(f"ERROR: Could not locate Vedabase root for {root}")

    records = []
    for path in iter_index_paths(root):
        record = summarize_page(path, vedabase_root)
        if page_types and record["page_type"] not in page_types:
            continue
        records.append(record)
        if limit is not None and len(records) >= limit:
            break

    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_root": str(root),
        "vedabase_root": str(vedabase_root),
        "summary": {
            "record_count": len(records),
            "page_type_counts": dict(Counter(record["page_type"] for record in records)),
            "work_counts": dict(Counter(record["work_id"] for record in records if record["work_id"])),
            "assembly_mode_counts": dict(Counter(record["assembly_mode"] for record in records if record["assembly_mode"])),
        },
        "records": records,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a manifest for a local Vedabase mirror")
    parser.add_argument("input_root")
    parser.add_argument("output")
    parser.add_argument(
        "--page-type",
        dest="page_types",
        action="append",
        choices=PAGE_TYPES,
        help="restrict records to one or more page types",
    )
    parser.add_argument("--limit", type=int, help="stop after N records")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    payload = build_manifest(
        Path(args.input_root),
        page_types=set(args.page_types) if args.page_types else None,
        limit=args.limit,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
