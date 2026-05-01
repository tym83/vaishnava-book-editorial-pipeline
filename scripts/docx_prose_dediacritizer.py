#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""
Remove Sanskrit diacritics from prose in DOCX while preserving them in shlokas and quote blocks.

v1 rules:
- preserve diacritics only in paragraph styles:
  * Шлока
  * Шлока в цитате
  * Цитата 1
  * Цитата 2
- dediacritize everywhere else, including headings, body, captions, footnotes, sources
- use a best-effort BBT-style prose mapping for common Sanskrit transliteration patterns

Examples:
  python3 docx_prose_dediacritizer.py normalize in.docx out.docx
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from typing import Dict, Iterable, Optional

from lxml import etree


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
W = f"{{{W_NS}}}"

PRESERVE_STYLES = {"Шлока", "Шлока в цитате", "Цитата 1", "Цитата 2"}

PRECOMPOSED_MAP = {
    "ā": "а",
    "Ā": "А",
    "ī": "и",
    "Ī": "И",
    "ū": "у",
    "Ū": "У",
    "ṛ": "ри",
    "Ṛ": "Ри",
    "ṝ": "ри",
    "Ṝ": "Ри",
    "ḷ": "ли",
    "Ḷ": "Ли",
    "ḹ": "ли",
    "Ḹ": "Ли",
    "ṃ": "м",
    "Ṃ": "М",
    "ṁ": "м",
    "Ṁ": "М",
    "ṅ": "н",
    "Ṅ": "Н",
    "ṇ": "н",
    "Ṇ": "Н",
    "ñ": "н",
    "Ñ": "Н",
    "ṭ": "т",
    "Ṭ": "Т",
    "ḍ": "д",
    "Ḍ": "Д",
    "ḥ": "х",
    "Ḥ": "Х",
    "ś": "ш",
    "Ś": "Ш",
    "ṣ": "ш",
    "Ṣ": "Ш",
}

COMBINING_MAP = {
    "̄": "",
    "̣": "",
    "̇": "",
    "̃": "",
    "́": "",
}


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def convert_doc_to_docx(path: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="docx-prose-dediacritizer-"))
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
        die("docx_prose_dediacritizer currently supports .docx and .doc")
    return path, None


def cleanup_temp(temp_dir: Optional[Path]) -> None:
    if temp_dir and temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)


class StyleCatalog:
    def __init__(self, root):
        self.by_id: Dict[str, etree._Element] = {}
        self.default_by_type: Dict[str, etree._Element] = {}
        for style in root.xpath(".//w:style", namespaces=NS):
            style_id = style.get(f"{W}styleId")
            if style_id:
                self.by_id[style_id] = style
            style_type = style.get(f"{W}type") or "unknown"
            if style.get(f"{W}default") in {"1", "true", "True"} and style_type not in self.default_by_type:
                self.default_by_type[style_type] = style

    def style_name(self, style_id: Optional[str]) -> Optional[str]:
        if not style_id:
            return None
        style = self.by_id.get(style_id)
        if style is None:
            return style_id
        name_node = style.find("w:name", namespaces=NS)
        return name_node.get(f"{W}val") if name_node is not None else style_id

    def default_style_name(self, style_type: str) -> Optional[str]:
        style = self.default_by_type.get(style_type)
        if style is None:
            return None
        name_node = style.find("w:name", namespaces=NS)
        return name_node.get(f"{W}val") if name_node is not None else style.get(f"{W}styleId")


def load_styles_root(z: zipfile.ZipFile):
    try:
        return etree.fromstring(z.read("word/styles.xml"))
    except KeyError:
        die("word/styles.xml not found in docx")


def iter_story_parts(z: zipfile.ZipFile) -> Iterable[tuple[str, etree._Element]]:
    for name in z.namelist():
        if name == "word/document.xml":
            yield name, etree.fromstring(z.read(name))
        elif name in {"word/footnotes.xml", "word/endnotes.xml", "word/comments.xml"}:
            yield name, etree.fromstring(z.read(name))
        elif (name.startswith("word/header") or name.startswith("word/footer")) and name.endswith(".xml"):
            yield name, etree.fromstring(z.read(name))


def iter_paragraphs_for_part(part_name: str, root):
    if part_name == "word/document.xml":
        return root.xpath(".//w:body//w:p", namespaces=NS)
    if part_name == "word/footnotes.xml":
        return root.xpath(".//w:footnote[not(@w:type)]//w:p", namespaces=NS)
    if part_name == "word/endnotes.xml":
        return root.xpath(".//w:endnote[not(@w:type)]//w:p", namespaces=NS)
    return root.xpath(".//w:p", namespaces=NS)


def get_paragraph_style_name(p, catalog: StyleCatalog, default_name: Optional[str]) -> Optional[str]:
    p_style = p.find("w:pPr/w:pStyle", namespaces=NS)
    if p_style is None:
        return default_name
    return catalog.style_name(p_style.get(f"{W}val"))


def dediacritize_text(text: str) -> str:
    if not text:
        return text

    out = text
    # Multi-char Cyrillic patterns that need more than simple mark stripping.
    pattern_replacements = [
        (r"Р̣", "Ри"),
        (r"р̣", "ри"),
        (r"Р̣̄", "Ри"),
        (r"р̣̄", "ри"),
        (r"Л̣", "Ли"),
        (r"л̣", "ли"),
        (r"Р̥", "Ри"),
        (r"р̥", "ри"),
        (r"Л̥", "Ли"),
        (r"л̥", "ли"),
    ]
    for pattern, repl in pattern_replacements:
        out = re.sub(pattern, repl, out)

    for src, dst in PRECOMPOSED_MAP.items():
        out = out.replace(src, dst)

    # Normalize then drop remaining combining marks.
    out = unicodedata.normalize("NFD", out)
    for src, dst in COMBINING_MAP.items():
        out = out.replace(src, dst)
    out = unicodedata.normalize("NFC", out)
    return out


def normalize_docx(src: Path, out: Path) -> dict:
    with zipfile.ZipFile(src, "r") as zin:
        styles_root = load_styles_root(zin)
        catalog = StyleCatalog(styles_root)
        default_paragraph_name = catalog.default_style_name("paragraph")

        part_roots = []
        for name, root in iter_story_parts(zin):
            part_roots.append((name, root))

        paragraph_changes = 0
        text_node_changes = 0

        for part_name, root in part_roots:
            for p in iter_paragraphs_for_part(part_name, root):
                style_name = get_paragraph_style_name(p, catalog, default_paragraph_name)
                if style_name in PRESERVE_STYLES:
                    continue
                changed_in_para = False
                for t in p.xpath(".//w:t", namespaces=NS):
                    original = t.text or ""
                    updated = dediacritize_text(original)
                    if updated != original:
                        t.text = updated
                        text_node_changes += 1
                        changed_in_para = True
                if changed_in_para:
                    paragraph_changes += 1

        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(src, "r") as zin2, zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            roots = {name: root for name, root in part_roots}
            for info in zin2.infolist():
                data = zin2.read(info.filename)
                if info.filename in roots:
                    zout.writestr(info, etree.tostring(roots[info.filename], xml_declaration=True, encoding="UTF-8", standalone="yes"))
                else:
                    zout.writestr(info, data)

    return {
        "input": str(src),
        "output": str(out),
        "paragraph_changes": paragraph_changes,
        "text_node_changes": text_node_changes,
    }


def cmd_normalize(args) -> None:
    src, temp_dir = resolve_source(Path(args.input))
    out = Path(args.output)
    try:
        summary = normalize_docx(src, out)
        print(f"Dediacritized prose: {summary['input']} -> {summary['output']}")
        print(f"Paragraphs changed: {summary['paragraph_changes']}")
        print(f"Text nodes changed: {summary['text_node_changes']}")
    finally:
        cleanup_temp(temp_dir)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Remove Sanskrit diacritics from prose in DOCX")
    sub = p.add_subparsers(dest="cmd", required=True)
    norm = sub.add_parser("normalize")
    norm.add_argument("input")
    norm.add_argument("output")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.cmd == "normalize":
        cmd_normalize(args)
    else:
        parser.error(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
