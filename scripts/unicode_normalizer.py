#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""
Normalize DOCX legacy Sanskrit/Cyrillic encoding to Unicode and optionally replace Gaura Times font.

v1 goals:
- replace known private-use / legacy symbols found in the current corpus
- replace font "Gaura Times" with a target Unicode font (default: Charis SIL)
- work on OOXML directly so document body, headers, footnotes, comments, etc. can be covered

Examples:
  python3 unicode_normalizer.py normalize in.docx out.docx
  python3 unicode_normalizer.py normalize in.docx out.docx --target-font "Charis SIL"
  python3 unicode_normalizer.py scan in.docx
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from lxml import etree


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}

# v1 mapping derived from the user's current corpus and checked against local vedabase mirror.
LEGACY_CHAR_MAP: Dict[str, str] = {
    "\uf101": "а̄",  # ā
    "\uf103": "д̣",  # ḍ
    "\uf109": "м̇",  # ṃ
    "\uf10f": "н̇",  # ṅ
    "\uf111": "н̣",  # ṇ
    "\uf113": "н̃",  # ñ
    "\uf115": "р̣",  # ṛ
    "\uf11b": "х̣",  # ḥ
    "\uf11d": "ш́",  # ś
    "\uf0be": "—",
}

# Real Unicode chars seen in the corpus that are valid and should be preserved.
KNOWN_VALID_NONASCII = {
    "ӣ",
    "ӯ",
    "ё",
    "Ё",
    "«",
    "»",
    "„",
    "”",
    "—",
    "–",
    "№",
    "…",
    "™",
    "é",
}

PRIVATE_USE_RANGES = (
    (0xE000, 0xF8FF),
    (0xF0000, 0xFFFFD),
    (0x100000, 0x10FFFD),
)

R_FONT_ATTRS = [
    f"{{{W_NS}}}ascii",
    f"{{{W_NS}}}hAnsi",
    f"{{{W_NS}}}cs",
    f"{{{W_NS}}}eastAsia",
]


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def convert_doc_to_docx(path: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="unicode-normalizer-"))
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


def resolve_source(path: Path) -> Tuple[Path, Path | None]:
    if not path.exists():
        die(f"Input file not found: {path}")
    if path.suffix.lower() == ".doc":
        converted = convert_doc_to_docx(path)
        return converted, converted.parent
    if path.suffix.lower() != ".docx":
        die("unicode_normalizer currently supports .docx and .doc")
    return path, None


def cleanup_temp(temp_dir: Path | None) -> None:
    if temp_dir and temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)


def replace_text(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    changes = []
    out = text
    for src, dst in LEGACY_CHAR_MAP.items():
        if src in out:
            out = out.replace(src, dst)
            changes.append((src, dst))
    return out, changes


def is_private_use(ch: str) -> bool:
    code = ord(ch)
    for start, end in PRIVATE_USE_RANGES:
        if start <= code <= end:
            return True
    return False


def xml_doc_from_bytes(data: bytes):
    parser = etree.XMLParser(remove_blank_text=False, recover=True)
    return etree.fromstring(data, parser=parser)


def xml_to_bytes(root) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone="yes")


def update_font_nodes(root, source_font: str, target_font: str) -> int:
    changed = 0
    for rfonts in root.xpath(".//w:rFonts", namespaces=NS):
        for attr in R_FONT_ATTRS:
            if rfonts.get(attr) == source_font:
                rfonts.set(attr, target_font)
                changed += 1
    font_name_attr = f"{{{W_NS}}}name"
    for font_node in root.xpath(".//w:font", namespaces=NS):
        if font_node.get(font_name_attr) == source_font:
            font_node.set(font_name_attr, target_font)
            changed += 1
    for alt_name in root.xpath(".//w:altName", namespaces=NS):
        if alt_name.get(font_name_attr) == source_font:
            alt_name.set(font_name_attr, target_font)
            changed += 1
    return changed


def normalize_xml_bytes(data: bytes, source_font: str, target_font: str) -> Tuple[bytes, dict]:
    root = xml_doc_from_bytes(data)
    text_replacements = 0
    replacement_types: Dict[str, int] = {}
    font_changes = update_font_nodes(root, source_font, target_font)

    for t in root.xpath(".//w:t", namespaces=NS):
        original = t.text or ""
        updated, changes = replace_text(original)
        if updated != original:
            t.text = updated
            text_replacements += 1
            for src, _dst in changes:
                replacement_types[src] = replacement_types.get(src, 0) + original.count(src)

    return xml_to_bytes(root), {
        "text_nodes_changed": text_replacements,
        "font_nodes_changed": font_changes,
        "replacement_types": replacement_types,
    }


def normalize_docx(src: Path, out: Path, source_font: str, target_font: str) -> dict:
    xml_targets = {
        "word/document.xml",
        "word/styles.xml",
        "word/stylesWithEffects.xml",
        "word/fontTable.xml",
        "word/footnotes.xml",
        "word/endnotes.xml",
        "word/comments.xml",
    }
    prefixes = ("word/header", "word/footer")

    summary = {
        "files_changed": 0,
        "text_nodes_changed": 0,
        "font_nodes_changed": 0,
        "replacement_types": {},
    }

    with zipfile.ZipFile(src, "r") as zin, zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            should_process = info.filename in xml_targets or any(info.filename.startswith(p) and info.filename.endswith(".xml") for p in prefixes)
            if should_process:
                normalized, local = normalize_xml_bytes(data, source_font=source_font, target_font=target_font)
                zout.writestr(info, normalized)
                if (
                    local["text_nodes_changed"]
                    or local["font_nodes_changed"]
                ):
                    summary["files_changed"] += 1
                    summary["text_nodes_changed"] += local["text_nodes_changed"]
                    summary["font_nodes_changed"] += local["font_nodes_changed"]
                    for k, v in local["replacement_types"].items():
                        summary["replacement_types"][k] = summary["replacement_types"].get(k, 0) + v
            else:
                zout.writestr(info, data)
    return summary


def scan_docx(src: Path) -> dict:
    counts: Dict[str, int] = {}
    unknown_private_use: Dict[str, int] = {}
    gaura_refs = 0
    with zipfile.ZipFile(src, "r") as z:
        for name in z.namelist():
            if not name.startswith("word/") or not name.endswith(".xml"):
                continue
            data = z.read(name).decode("utf-8", "ignore")
            gaura_refs += data.count("Gaura Times")
            for ch in LEGACY_CHAR_MAP:
                if ch in data:
                    counts[ch] = counts.get(ch, 0) + data.count(ch)
            for ch in data:
                if is_private_use(ch) and ch not in LEGACY_CHAR_MAP:
                    unknown_private_use[ch] = unknown_private_use.get(ch, 0) + 1
    return {
        "gaura_refs": gaura_refs,
        "legacy_counts": counts,
        "unknown_private_use": unknown_private_use,
    }


def cmd_scan(args) -> None:
    src, temp_dir = resolve_source(Path(args.input))
    try:
        result = scan_docx(src)
        print(f"Input: {src}")
        print(f"Gaura Times refs: {result['gaura_refs']}")
        if not result["legacy_counts"]:
            print("Legacy/private-use chars: none found")
            return
        print("Legacy/private-use chars:")
        for ch, count in sorted(result["legacy_counts"].items(), key=lambda kv: ord(kv[0])):
            mapped = LEGACY_CHAR_MAP.get(ch, "?")
            print(f"  {hex(ord(ch))} {repr(ch)} x{count} -> {mapped}")
        if result["unknown_private_use"]:
            print("Unknown private-use chars:")
            for ch, count in sorted(result["unknown_private_use"].items(), key=lambda kv: ord(kv[0])):
                category = unicodedata.name(ch, "PRIVATE USE")
                print(f"  {hex(ord(ch))} {repr(ch)} x{count} -> {category}")
    finally:
        cleanup_temp(temp_dir)


def cmd_normalize(args) -> None:
    src, temp_dir = resolve_source(Path(args.input))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        summary = normalize_docx(src, out, source_font=args.source_font, target_font=args.target_font)
        print(f"Normalized: {src} -> {out}")
        print(f"Files changed: {summary['files_changed']}")
        print(f"Text nodes changed: {summary['text_nodes_changed']}")
        print(f"Font nodes changed: {summary['font_nodes_changed']}")
        if summary["replacement_types"]:
            print("Replacement counts:")
            for ch, count in sorted(summary["replacement_types"].items(), key=lambda kv: ord(kv[0])):
                print(f"  {hex(ord(ch))} {repr(ch)} x{count} -> {LEGACY_CHAR_MAP[ch]}")
    finally:
        cleanup_temp(temp_dir)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Normalize legacy Gaura Times/private-use text to Unicode")
    sub = p.add_subparsers(dest="cmd", required=True)

    scan = sub.add_parser("scan")
    scan.add_argument("input")

    norm = sub.add_parser("normalize")
    norm.add_argument("input")
    norm.add_argument("output")
    norm.add_argument("--source-font", default="Gaura Times")
    norm.add_argument("--target-font", default="Charis SIL")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.cmd == "scan":
        cmd_scan(args)
    elif args.cmd == "normalize":
        cmd_normalize(args)
    else:
        parser.error(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
