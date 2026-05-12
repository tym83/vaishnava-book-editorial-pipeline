#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Normalize inline DOCX footnote marker placement.

Rule: a footnote marker belongs after the word/phrase it annotates, but before
the following punctuation mark:

    слово.<footnote>  ->  слово<footnote>.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

from lxml import etree


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"w": W_NS}
W = f"{{{W_NS}}}"
XML_SPACE = f"{{{XML_NS}}}space"

PUNCTUATION_RE = re.compile(r"([.,;:!?…]+)(\s*)$")


@dataclass
class Change:
    part: str
    paragraph_index: int
    footnote_id: str
    moved_text: str
    before_excerpt: str
    after_excerpt: str
    action: str


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def convert_doc_to_docx(path: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="docx-footnote-ref-"))
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
        die("docx_footnote_reference_normalizer supports .docx and .doc")
    return path, None


def cleanup_temp(temp_dir: Optional[Path]) -> None:
    if temp_dir and temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)


def visible_text(node) -> str:
    return "".join(t.text or "" for t in node.xpath(".//w:t", namespaces=NS))


def compact_excerpt(text: str, limit: int = 160) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def direct_runs(paragraph) -> List[etree._Element]:
    return paragraph.xpath("./w:r", namespaces=NS)


def run_text_nodes(run) -> List[etree._Element]:
    return run.xpath(".//w:t", namespaces=NS)


def update_xml_space(text_node) -> None:
    text = text_node.text or ""
    if text.startswith(" ") or text.endswith(" "):
        text_node.set(XML_SPACE, "preserve")
    else:
        text_node.attrib.pop(XML_SPACE, None)


def trim_trailing_punctuation(run) -> Optional[str]:
    for text_node in reversed(run_text_nodes(run)):
        text = text_node.text or ""
        match = PUNCTUATION_RE.search(text)
        if not match:
            continue
        moved = match.group(1) + match.group(2)
        text_node.text = text[: match.start()]
        update_xml_space(text_node)
        return moved
    return None


def run_has_content_except_empty_text(run) -> bool:
    for child in run:
        if child.tag == f"{W}rPr":
            continue
        if child.tag == f"{W}t" and not (child.text or ""):
            continue
        return True
    return False


def remove_run_if_empty(run) -> None:
    if run_has_content_except_empty_text(run):
        return
    parent = run.getparent()
    if parent is not None:
        parent.remove(run)


def text_run_like(source_run, text: str):
    run = etree.Element(f"{W}r")
    rpr = source_run.find("w:rPr", namespaces=NS)
    if rpr is not None:
        run.append(copy.deepcopy(rpr))
    text_node = etree.Element(f"{W}t")
    text_node.text = text
    update_xml_space(text_node)
    run.append(text_node)
    return run


def next_text_after_ref(runs: List[etree._Element], ref_index: int) -> str:
    for run in runs[ref_index + 1 :]:
        text = visible_text(run)
        if text:
            return text
    return ""


def previous_text_run(runs: List[etree._Element], ref_index: int) -> Optional[etree._Element]:
    for run in reversed(runs[:ref_index]):
        if visible_text(run):
            return run
    return None


def starts_with_same_punctuation(text: str, moved_text: str) -> bool:
    stripped = text.lstrip()
    moved = moved_text.strip()
    return bool(moved) and stripped.startswith(moved)


def normalize_paragraph(part_name: str, paragraph_index: int, paragraph) -> List[Change]:
    changes: List[Change] = []
    for ref_run in list(paragraph.xpath("./w:r[w:footnoteReference]", namespaces=NS)):
        runs = direct_runs(paragraph)
        if ref_run not in runs:
            continue
        ref_index = runs.index(ref_run)
        prev_run = previous_text_run(runs, ref_index)
        if prev_run is None:
            continue

        before = visible_text(paragraph)
        moved = trim_trailing_punctuation(prev_run)
        if not moved:
            continue

        footnote = ref_run.find("w:footnoteReference", namespaces=NS)
        footnote_id = footnote.get(f"{W}id") if footnote is not None else ""
        next_text = next_text_after_ref(runs, ref_index)
        action = "moved_before_punctuation"
        if starts_with_same_punctuation(next_text, moved):
            action = "removed_duplicate_before_footnote"
        else:
            ref_run.addnext(text_run_like(prev_run, moved))
        remove_run_if_empty(prev_run)

        after = visible_text(paragraph)
        changes.append(
            Change(
                part=part_name,
                paragraph_index=paragraph_index,
                footnote_id=footnote_id,
                moved_text=moved,
                before_excerpt=compact_excerpt(before),
                after_excerpt=compact_excerpt(after),
                action=action,
            )
        )
    return changes


def normalize_docx(src: Path, out: Path, report_json: Optional[Path] = None, report_md: Optional[Path] = None) -> dict:
    with zipfile.ZipFile(src, "r") as zin:
        document_root = etree.fromstring(zin.read("word/document.xml"))
        changes: List[Change] = []
        for idx, paragraph in enumerate(document_root.xpath(".//w:body//w:p", namespaces=NS), 1):
            changes.extend(normalize_paragraph("word/document.xml", idx, paragraph))

        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(src, "r") as zin2, zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for info in zin2.infolist():
                data = zin2.read(info.filename)
                if info.filename == "word/document.xml":
                    data = etree.tostring(document_root, xml_declaration=True, encoding="UTF-8", standalone="yes")
                zout.writestr(info, data)

    summary = {
        "input": str(src),
        "output": str(out),
        "changes": len(changes),
        "actions": {},
        "changed_footnote_ids": [change.footnote_id for change in changes],
        "examples": [asdict(change) for change in changes[:40]],
    }
    for change in changes:
        summary["actions"][change.action] = summary["actions"].get(change.action, 0) + 1

    if report_json:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if report_md:
        write_report_md(report_md, summary)
    return summary


def write_report_md(path: Path, summary: dict) -> None:
    lines = [
        "# DOCX Footnote Reference Normalizer",
        "",
        f"- input: `{summary['input']}`",
        f"- output: `{summary['output']}`",
        f"- changes: {summary['changes']}",
        "",
        "## Actions",
        "",
    ]
    if not summary["actions"]:
        lines.append("- none")
    else:
        for key, value in sorted(summary["actions"].items()):
            lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Examples", ""])
    if not summary["examples"]:
        lines.append("- none")
    else:
        for item in summary["examples"]:
            lines.append(
                f"- `{item['part']}#{item['paragraph_index']}` footnote `{item['footnote_id']}`: "
                f"{item['action']}, moved `{item['moved_text']}`; "
                f"visible text unchanged: `{item['after_excerpt']}`"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_normalize(args) -> None:
    src, temp_dir = resolve_source(Path(args.input))
    try:
        summary = normalize_docx(
            src,
            Path(args.output),
            report_json=Path(args.report_json) if args.report_json else None,
            report_md=Path(args.report_md) if args.report_md else None,
        )
        print(f"Normalized footnote references: {summary['input']} -> {summary['output']}")
        print(f"Changes: {summary['changes']}")
        print(f"Actions: {summary['actions']}")
    finally:
        cleanup_temp(temp_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalize inline DOCX footnote reference placement")
    sub = parser.add_subparsers(dest="command", required=True)
    normalize = sub.add_parser("normalize")
    normalize.add_argument("input")
    normalize.add_argument("output")
    normalize.add_argument("--report-json")
    normalize.add_argument("--report-md")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "normalize":
        cmd_normalize(args)
        return 0
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
