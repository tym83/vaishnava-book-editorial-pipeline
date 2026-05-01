#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Normalize sources into a machine-readable structural JSON layer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from text_structure import cleanup_temp, normalize_source, write_document_json


SUPPORTED_SUFFIXES = {".doc", ".docx", ".txt", ".md", ".html", ".htm"}


def normalize_one(input_path: Path, output_path: Path, source_format: str) -> dict:
    document, temp_dir = normalize_source(input_path, forced_format=source_format)
    try:
        write_document_json(document, output_path)
        return document.to_dict()
    finally:
        cleanup_temp(temp_dir)


def normalize_dir(input_dir: Path, output_dir: Path, source_format: str) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized = []
    skipped = []
    for path in sorted(input_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            skipped.append(str(path))
            continue
        rel = path.relative_to(input_dir)
        out_path = (output_dir / rel).with_suffix(".json")
        normalized.append(
            {
                "input": str(path),
                "output": str(out_path),
                "summary": normalize_one(path, out_path, source_format),
            }
        )
    return {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "normalized_count": len(normalized),
        "skipped_count": len(skipped),
        "normalized": normalized,
        "skipped": skipped,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalize structured text sources into JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    p_norm = sub.add_parser("normalize", help="normalize one file")
    p_norm.add_argument("input")
    p_norm.add_argument("output")
    p_norm.add_argument(
        "--format",
        default="auto",
        choices=["auto", "doc", "docx", "text", "html", "vedabase_html"],
        help="force input format",
    )

    p_dir = sub.add_parser("normalize-dir", help="normalize a directory tree")
    p_dir.add_argument("input_dir")
    p_dir.add_argument("output_dir")
    p_dir.add_argument(
        "--format",
        default="auto",
        choices=["auto", "doc", "docx", "text", "html", "vedabase_html"],
        help="force input format for all files",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "normalize":
        summary = normalize_one(Path(args.input), Path(args.output), args.format)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    if args.command == "normalize-dir":
        summary = normalize_dir(Path(args.input_dir), Path(args.output_dir), args.format)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
