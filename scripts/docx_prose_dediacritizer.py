#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""
Remove Sanskrit diacritics from Russian prose in DOCX while preserving them in Sanskrit/transliteration blocks.

v1 rules:
- preserve diacritics in paragraph styles:
  * Шлока
  * Шлока в цитате
- preserve quote/body paragraphs that look like standalone Sanskrit transliteration
- dediacritize Russian prose, including headings, body, captions, footnotes, sources
- use a best-effort BBT-style prose mapping for common Sanskrit transliteration patterns

Examples:
  python3 docx_prose_dediacritizer.py normalize in.docx out.docx
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, Iterable, Optional

from lxml import etree

from sanskrit_diacritics import classify_diacritic_context, dediacritize_text as policy_dediacritize_text


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
W = f"{{{W_NS}}}"


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


def visible_text(p) -> str:
    chunks = []
    for node in p.xpath(".//w:t | .//w:tab | .//w:br | .//w:cr", namespaces=NS):
        if node.tag == f"{W}t":
            chunks.append(node.text or "")
        elif node.tag == f"{W}tab":
            chunks.append("\t")
        else:
            chunks.append("\n")
    return "".join(chunks)


def text_nodes(p) -> list:
    return p.xpath(".//w:t", namespaces=NS)


def joined_text_nodes(nodes: list) -> str:
    return "".join(node.text or "" for node in nodes)


def redistribute_equal_length_text(nodes: list, text: str) -> int:
    changed_nodes = 0
    offset = 0
    for node in nodes:
        original = node.text or ""
        updated = text[offset : offset + len(original)]
        offset += len(original)
        if updated != original:
            node.text = updated
            changed_nodes += 1
    return changed_nodes


def short_excerpt(text: str, limit: int = 180) -> str:
    cleaned = " ".join(str(text or "").replace("\u00a0", " ").split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1]}…"


def add_example(examples: list[dict], item: dict, limit: int = 12) -> None:
    if len(examples) < limit:
        examples.append(item)


def write_report_md(path: Path, summary: dict) -> None:
    reasons = summary.get("decision_reasons", {})
    lines = [
        "# Prose Dediacritizer Report",
        "",
        f"- input: `{summary['input']}`",
        f"- output: `{summary['output']}`",
        f"- paragraphs changed: {summary['paragraph_changes']}",
        f"- text nodes changed: {summary['text_node_changes']}",
        f"- paragraph-level post replacements: {summary['paragraph_level_post_replacements']}",
        f"- normalized prose paragraphs: {summary['normalized_prose_paragraphs']}",
        f"- preserved paragraphs: {summary['preserved_paragraphs']}",
        f"- paragraphs without diacritics: {summary['no_diacritics_paragraphs']}",
        "",
        "## Decision Reasons",
        "",
    ]
    for reason, count in sorted(reasons.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- `{reason}`: {count}")
    lines.extend(["", "## Changed Examples", ""])
    for item in summary.get("changed_examples", []):
        lines.append(
            f"- `{item['part']}` paragraph {item['paragraph_index']} style `{item.get('style_name') or ''}`: "
            f"{item['before']} -> {item['after']}"
        )
    lines.extend(["", "## Preserved Examples", ""])
    for item in summary.get("preserved_examples", []):
        lines.append(
            f"- `{item['part']}` paragraph {item['paragraph_index']} style `{item.get('style_name') or ''}` "
            f"reason `{item['reason']}`: {item['text']}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def normalize_docx(src: Path, out: Path, report_json: Optional[Path] = None, report_md: Optional[Path] = None) -> dict:
    with zipfile.ZipFile(src, "r") as zin:
        styles_root = load_styles_root(zin)
        catalog = StyleCatalog(styles_root)
        default_paragraph_name = catalog.default_style_name("paragraph")

        part_roots = []
        for name, root in iter_story_parts(zin):
            part_roots.append((name, root))

        paragraph_changes = 0
        text_node_changes = 0
        paragraph_level_post_replacements = 0
        preserved_paragraphs = 0
        normalized_prose_paragraphs = 0
        no_diacritics_paragraphs = 0
        decision_reasons: Dict[str, int] = {}
        changed_examples: list[dict] = []
        preserved_examples: list[dict] = []

        for part_name, root in part_roots:
            for paragraph_index, p in enumerate(iter_paragraphs_for_part(part_name, root), start=1):
                style_name = get_paragraph_style_name(p, catalog, default_paragraph_name)
                para_text = visible_text(p)
                decision = classify_diacritic_context(para_text, style_name=style_name)
                decision_reasons[decision.reason] = decision_reasons.get(decision.reason, 0) + 1
                if decision.action == "none":
                    no_diacritics_paragraphs += 1
                    continue
                if decision.action == "preserve":
                    preserved_paragraphs += 1
                    add_example(
                        preserved_examples,
                        {
                            "part": part_name,
                            "paragraph_index": paragraph_index,
                            "style_name": style_name,
                            "reason": decision.reason,
                            "stats": decision.stats.to_dict(),
                            "text": short_excerpt(para_text),
                        },
                    )
                    continue

                changed_in_para = False
                before_text = para_text
                nodes = text_nodes(p)
                for t in nodes:
                    original = t.text or ""
                    updated = policy_dediacritize_text(original)
                    if updated != original:
                        t.text = updated
                        text_node_changes += 1
                        changed_in_para = True
                joined = joined_text_nodes(nodes)
                joined_updated = policy_dediacritize_text(joined)
                if joined_updated != joined and len(joined_updated) == len(joined):
                    text_node_changes += redistribute_equal_length_text(nodes, joined_updated)
                    paragraph_level_post_replacements += 1
                    changed_in_para = True
                if changed_in_para:
                    after_text = visible_text(p)
                    paragraph_changes += 1
                    normalized_prose_paragraphs += 1
                    add_example(
                        changed_examples,
                        {
                            "part": part_name,
                            "paragraph_index": paragraph_index,
                            "style_name": style_name,
                            "reason": decision.reason,
                            "stats": decision.stats.to_dict(),
                            "before": short_excerpt(before_text),
                            "after": short_excerpt(after_text),
                        },
                    )

        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(src, "r") as zin2, zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            roots = {name: root for name, root in part_roots}
            for info in zin2.infolist():
                data = zin2.read(info.filename)
                if info.filename in roots:
                    zout.writestr(info, etree.tostring(roots[info.filename], xml_declaration=True, encoding="UTF-8", standalone="yes"))
                else:
                    zout.writestr(info, data)

    summary = {
        "input": str(src),
        "output": str(out),
        "paragraph_changes": paragraph_changes,
        "text_node_changes": text_node_changes,
        "paragraph_level_post_replacements": paragraph_level_post_replacements,
        "normalized_prose_paragraphs": normalized_prose_paragraphs,
        "preserved_paragraphs": preserved_paragraphs,
        "no_diacritics_paragraphs": no_diacritics_paragraphs,
        "decision_reasons": decision_reasons,
        "changed_examples": changed_examples,
        "preserved_examples": preserved_examples,
    }
    if report_json:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report_md:
        write_report_md(report_md, summary)
    return summary


def cmd_normalize(args) -> None:
    src, temp_dir = resolve_source(Path(args.input))
    out = Path(args.output)
    try:
        summary = normalize_docx(
            src,
            out,
            report_json=Path(args.report_json) if args.report_json else None,
            report_md=Path(args.report_md) if args.report_md else None,
        )
        print(f"Dediacritized prose: {summary['input']} -> {summary['output']}")
        print(f"Paragraphs changed: {summary['paragraph_changes']}")
        print(f"Text nodes changed: {summary['text_node_changes']}")
        print(f"Paragraph-level post replacements: {summary['paragraph_level_post_replacements']}")
        print(f"Preserved paragraphs: {summary['preserved_paragraphs']}")
    finally:
        cleanup_temp(temp_dir)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Remove Sanskrit diacritics from prose in DOCX")
    sub = p.add_subparsers(dest="cmd", required=True)
    norm = sub.add_parser("normalize")
    norm.add_argument("input")
    norm.add_argument("output")
    norm.add_argument("--report-json")
    norm.add_argument("--report-md")
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
