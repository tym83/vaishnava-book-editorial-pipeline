#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Normalize low-risk typography in DOCX text nodes.

The script deliberately avoids semantic rewrites.  It keeps run structure and
only changes text inside existing ``w:t`` nodes.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Dict, Optional

from lxml import etree


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"w": W_NS}
W = f"{{{W_NS}}}"
XML_SPACE = f"{{{XML_NS}}}space"
DOCX_TEXT_PARTS = {"word/document.xml", "word/footnotes.xml", "word/endnotes.xml"}


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def convert_doc_to_docx(path: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="docx-typography-"))
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


def resolve_source(path: Path) -> tuple[Path, Optional[Path]]:
    if not path.exists():
        die(f"Input file not found: {path}")
    if path.suffix.lower() == ".doc":
        converted = convert_doc_to_docx(path)
        return converted, converted.parent
    if path.suffix.lower() != ".docx":
        die("docx_typography_normalizer supports .docx and .doc")
    return path, None


def cleanup_temp(temp_dir: Optional[Path]) -> None:
    if temp_dir and temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)


def set_text(node: etree._Element, value: str) -> None:
    node.text = value
    if value.startswith(" ") or value.endswith(" "):
        node.set(XML_SPACE, "preserve")
    else:
        node.attrib.pop(XML_SPACE, None)


def next_nonspace(text: str, start: int) -> str:
    for char in text[start:]:
        if not char.isspace():
            return char
    return ""


def quote_replacements(full_text: str) -> list[str]:
    quote_count = full_text.count('"')
    if quote_count == 0 or quote_count % 2 != 0:
        return []
    if "«" in full_text or "»" in full_text:
        return ["„" if idx % 2 == 0 else "“" for idx in range(quote_count)]
    if quote_count == 2:
        return ["«", "»"]
    if quote_count == 4:
        positions = [idx for idx, char in enumerate(full_text) if char == '"']
        after_second = next_nonspace(full_text, positions[1] + 1)
        if re.match(r"[А-ЯЁа-яёA-Za-z0-9]", after_second or ""):
            return ["«", "„", "“", "»"]
        return ["«", "»", "«", "»"]
    return ["«" if idx % 2 == 0 else "»" for idx in range(quote_count)]


def replace_straight_quotes(text: str, quote_index: int, replacements: list[str]) -> tuple[str, int, int]:
    changed = 0
    out = []
    for char in text:
        if char == '"':
            quote_index += 1
            out.append(replacements[quote_index - 1])
            changed += 1
        else:
            out.append(char)
    return "".join(out), quote_index, changed


def normalize_node_text(text: str) -> tuple[str, Counter]:
    counts: Counter = Counter()
    new = text.replace("\u00a0", " ")
    if new != text:
        counts["nbsp_to_space"] += text.count("\u00a0")
    before = new
    new = re.sub(r"[ \t]{2,}", " ", new)
    if new != before:
        counts["double_spaces"] += 1
    before = new
    new = re.sub(r"\s+([,.;:!?…])", r"\1", new)
    if new != before:
        counts["space_before_punctuation"] += 1
    before = new
    new = new.replace("...", "…")
    if new != before:
        counts["three_dots"] += 1
    before = new
    new = re.sub(r"»([^«»]{1,200})«", r"„\1“", new)
    if new != before:
        counts["inverted_nested_guillemets"] += 1
    before = new
    new = re.sub(r"(?<=[А-ЯЁа-яёA-Za-z0-9])\s+-\s+(?=[А-ЯЁа-яёA-Za-z0-9])", " — ", new)
    if new != before:
        counts["spaced_ascii_dash"] += 1
    before = new
    new = re.sub(r"([,;:!?])(?=[А-ЯЁа-яёA-Za-z])", r"\1 ", new)
    if new != before:
        counts["space_after_punctuation"] += 1
    return new, counts


def normalize_part(root: etree._Element) -> Dict[str, object]:
    counts: Counter = Counter()
    changed_nodes = 0
    changed_paragraphs = 0
    for paragraph in root.xpath(".//w:p", namespaces=NS):
        paragraph_changed = False
        quote_index = 0
        full_text = "".join(node.text or "" for node in paragraph.xpath(".//w:t", namespaces=NS))
        replacements = quote_replacements(full_text)
        for node in paragraph.xpath(".//w:t", namespaces=NS):
            old = node.text or ""
            new, node_counts = normalize_node_text(old)
            if replacements:
                new, quote_index, quote_count = replace_straight_quotes(
                    new,
                    quote_index,
                    replacements,
                )
                if quote_count:
                    node_counts["straight_quotes"] += quote_count
            if new != old:
                set_text(node, new)
                changed_nodes += 1
                paragraph_changed = True
                counts.update(node_counts)
        if paragraph_changed:
            changed_paragraphs += 1
    return {
        "changed_paragraphs": changed_paragraphs,
        "changed_text_nodes": changed_nodes,
        "actions": dict(sorted(counts.items())),
    }


def normalize_docx(src: Path, out: Path, report_json: Optional[Path], report_md: Optional[Path]) -> Dict[str, object]:
    out.parent.mkdir(parents=True, exist_ok=True)
    parts: Dict[str, object] = {}
    with zipfile.ZipFile(src, "r") as zin, zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename in DOCX_TEXT_PARTS:
                root = etree.fromstring(data)
                part_summary = normalize_part(root)
                parts[info.filename] = part_summary
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone="yes")
            zout.writestr(info, data)

    summary = {
        "input": str(src),
        "output": str(out),
        "parts": parts,
    }
    if report_json:
        report_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report_md:
        lines = [
            "# DOCX Typography Normalizer",
            "",
            f"Input: `{src}`",
            f"Output: `{out}`",
            "",
            "| Part | Paragraphs | Text nodes | Actions |",
            "|---|---:|---:|---|",
        ]
        for part, item in parts.items():
            actions = ", ".join(f"{key}: {value}" for key, value in item["actions"].items()) or "-"
            lines.append(f"| `{part}` | {item['changed_paragraphs']} | {item['changed_text_nodes']} | {actions} |")
        report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def cmd_normalize(args) -> None:
    src, temp_dir = resolve_source(Path(args.input))
    try:
        summary = normalize_docx(
            src,
            Path(args.output),
            Path(args.report_json) if args.report_json else None,
            Path(args.report_md) if args.report_md else None,
        )
        total_nodes = sum(part["changed_text_nodes"] for part in summary["parts"].values())
        print(f"Normalized typography: {summary['input']} -> {summary['output']}")
        print(f"Changed text nodes: {total_nodes}")
    finally:
        cleanup_temp(temp_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalize low-risk DOCX typography")
    sub = parser.add_subparsers(dest="cmd", required=True)
    normalize = sub.add_parser("normalize")
    normalize.add_argument("input")
    normalize.add_argument("output")
    normalize.add_argument("--report-json")
    normalize.add_argument("--report-md")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.cmd == "normalize":
        cmd_normalize(args)
        return 0
    parser.error(f"Unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
