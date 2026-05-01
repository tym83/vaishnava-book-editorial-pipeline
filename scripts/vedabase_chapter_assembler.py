#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Assemble Vedabase chapter-level JSON from advanced-view or verse pages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from text_structure import assemble_vedabase_chapter, parse_vedabase_path


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def assemble_one(input_path: Path, output_path: Path) -> Dict[str, object]:
    chapter = assemble_vedabase_chapter(input_path)
    payload = chapter.to_dict()
    write_json(output_path, payload)
    return payload


def collect_chapter_inputs(root: Path) -> List[Path]:
    chapter_paths = []
    seen = set()
    for path in sorted(root.rglob("index.html")):
        info = parse_vedabase_path(path)
        if info.page_type != "chapter":
            continue
        if info.web_path in seen:
            continue
        seen.add(info.web_path)
        chapter_paths.append(path)
    return chapter_paths


def output_path_for_chapter(output_dir: Path, payload: Dict[str, object]) -> Path:
    web_path = str(payload.get("metadata", {}).get("vedabase_path") or "").strip("/")
    if not web_path:
        raise SystemExit("ERROR: assembled chapter payload does not contain metadata.vedabase_path")
    return output_dir / web_path / "chapter.json"


def assemble_dir(input_root: Path, output_dir: Path, limit: Optional[int] = None) -> Dict[str, object]:
    chapter_inputs = collect_chapter_inputs(input_root)
    assembled = []
    errors = []
    for path in chapter_inputs:
        if limit is not None and len(assembled) >= limit:
            break
        try:
            chapter = assemble_vedabase_chapter(path)
            payload = chapter.to_dict()
            out_path = output_path_for_chapter(output_dir, payload)
            write_json(out_path, payload)
            assembled.append(
                {
                    "input": str(path),
                    "output": str(out_path),
                    "source_mode": payload.get("metadata", {}).get("source_mode"),
                    "verse_count": payload.get("metadata", {}).get("verse_count"),
                    "block_count": payload.get("metadata", {}).get("block_count"),
                    "vedabase_path": payload.get("metadata", {}).get("vedabase_path"),
                }
            )
        except SystemExit as exc:
            errors.append({"input": str(path), "error": str(exc)})

    return {
        "input_root": str(input_root),
        "output_dir": str(output_dir),
        "assembled_count": len(assembled),
        "error_count": len(errors),
        "assembled": assembled,
        "errors": errors,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Assemble Vedabase chapter JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    p_one = sub.add_parser("assemble", help="assemble one chapter")
    p_one.add_argument("input")
    p_one.add_argument("output")

    p_dir = sub.add_parser("assemble-dir", help="assemble all detected chapters under a root")
    p_dir.add_argument("input_root")
    p_dir.add_argument("output_dir")
    p_dir.add_argument("--limit", type=int, help="stop after N assembled chapters")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "assemble":
        payload = assemble_one(Path(args.input), Path(args.output))
        print(json.dumps(payload["metadata"], ensure_ascii=False, indent=2))
        return 0

    if args.command == "assemble-dir":
        summary = assemble_dir(Path(args.input_root), Path(args.output_dir), limit=args.limit)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
