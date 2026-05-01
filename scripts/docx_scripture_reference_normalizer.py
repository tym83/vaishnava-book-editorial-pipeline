#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Normalize scripture reference formatting inside DOCX files."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from lxml import etree

from vedabase_reference_resolver import (
    BG_PATTERN,
    CC_PATTERN,
    ISO_PATTERN,
    SB_PATTERN,
    format_reference_display,
    normalize_lila_token,
    normalize_range_token,
)


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
W = f"{{{W_NS}}}"


@dataclass
class Replacement:
    part: str
    paragraph_index_in_part: int
    container_id: Optional[str]
    node_index_in_paragraph: int
    before: str
    after: str
    changed_matches: List[Dict[str, str]]


@dataclass
class ReferenceMatch:
    raw: str
    replacement: str
    start: int
    end: int


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def convert_doc_to_docx(path: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="docx-scripture-ref-"))
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


def resolve_docx(path: Path) -> Tuple[Path, Optional[Path]]:
    if not path.exists():
        die(f"Input file not found: {path}")
    if path.suffix.lower() == ".doc":
        converted = convert_doc_to_docx(path)
        return converted, converted.parent
    if path.suffix.lower() != ".docx":
        die("docx_scripture_reference_normalizer supports .docx and .doc only")
    return path, None


def cleanup_temp(temp_dir: Optional[Path]) -> None:
    if temp_dir and temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)


def xml_doc_from_bytes(data: bytes):
    parser = etree.XMLParser(remove_blank_text=False, recover=True)
    return etree.fromstring(data, parser=parser)


def xml_to_bytes(root) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone="yes")


def iter_paragraphs_for_part(part_name: str, root) -> List[Tuple[int, Optional[str], etree._Element]]:
    rows: List[Tuple[int, Optional[str], etree._Element]] = []
    if part_name == "word/document.xml":
        for idx, para in enumerate(root.xpath(".//w:body/w:p", namespaces=NS), 1):
            rows.append((idx, None, para))
        return rows
    if part_name == "word/footnotes.xml":
        idx = 0
        for footnote in root.xpath(".//w:footnote[not(@w:type)]", namespaces=NS):
            footnote_id = footnote.get(f"{W}id")
            for para in footnote.findall("w:p", namespaces=NS):
                idx += 1
                rows.append((idx, footnote_id, para))
        return rows
    if part_name == "word/endnotes.xml":
        idx = 0
        for endnote in root.xpath(".//w:endnote[not(@w:type)]", namespaces=NS):
            endnote_id = endnote.get(f"{W}id")
            for para in endnote.findall("w:p", namespaces=NS):
                idx += 1
                rows.append((idx, endnote_id, para))
        return rows
    if part_name == "word/comments.xml":
        idx = 0
        for comment in root.xpath(".//w:comment", namespaces=NS):
            comment_id = comment.get(f"{W}id")
            for para in comment.findall("w:p", namespaces=NS):
                idx += 1
                rows.append((idx, comment_id, para))
        return rows
    if part_name.startswith("word/header") or part_name.startswith("word/footer"):
        for idx, para in enumerate(root.xpath(".//w:p", namespaces=NS), 1):
            rows.append((idx, None, para))
        return rows
    return rows


def canonical_bg(match) -> str:
    chapter = match.group("chapter")
    verse = normalize_range_token(match.group("verse"))
    return format_reference_display("bg", ["bg", chapter, verse], nbsp=True)


def canonical_sb(match) -> str:
    canto = match.group("canto")
    chapter = match.group("chapter")
    verse = normalize_range_token(match.group("verse"))
    return format_reference_display("sb", ["sb", canto, chapter, verse], nbsp=True)


def canonical_cc(match) -> str:
    lila = normalize_lila_token(match.group("lila"))
    if not lila:
        return match.group("raw")
    chapter = match.group("chapter")
    verse = normalize_range_token(match.group("verse"))
    return format_reference_display(f"cc/{lila}", ["cc", lila, chapter, verse], nbsp=True)


def canonical_iso(match) -> str:
    verse = normalize_range_token(match.group("verse"))
    return format_reference_display("iso", ["iso", verse], nbsp=True)


def collect_reference_matches(text: str) -> List[ReferenceMatch]:
    matches: List[ReferenceMatch] = []

    def append_matches(pattern, builder) -> None:
        for match in pattern.finditer(text):
            raw = match.group("raw")
            replacement = builder(match)
            if raw == replacement:
                continue
            matches.append(
                ReferenceMatch(
                    raw=raw,
                    replacement=replacement,
                    start=match.start(),
                    end=match.end(),
                )
            )

    append_matches(BG_PATTERN, canonical_bg)
    append_matches(SB_PATTERN, canonical_sb)
    append_matches(CC_PATTERN, canonical_cc)
    append_matches(ISO_PATTERN, canonical_iso)
    matches.sort(key=lambda item: (item.start, item.end))
    return matches


def normalize_text_node(text: str) -> Tuple[str, List[Dict[str, str]]]:
    changed_matches: List[Dict[str, str]] = []
    out = text

    def replace(pattern, builder):
        nonlocal out

        def repl(match):
            raw = match.group("raw")
            replacement = builder(match)
            if raw != replacement:
                changed_matches.append({"raw": raw, "replacement": replacement})
            return replacement

        out = pattern.sub(repl, out)

    replace(BG_PATTERN, canonical_bg)
    replace(SB_PATTERN, canonical_sb)
    replace(CC_PATTERN, canonical_cc)
    replace(ISO_PATTERN, canonical_iso)
    return out, changed_matches


def apply_cross_node_matches(
    text_nodes: List[etree._Element],
    part_name: str,
    paragraph_index: int,
    container_id: Optional[str],
) -> List[Replacement]:
    texts = [node.text or "" for node in text_nodes]
    if len(text_nodes) < 2 or not any(texts):
        return []

    spans: List[Tuple[int, int]] = []
    cursor = 0
    for text in texts:
        spans.append((cursor, cursor + len(text)))
        cursor += len(text)

    joined = "".join(texts)
    replacements: List[Replacement] = []
    for match in reversed(collect_reference_matches(joined)):
        affected_indexes = [
            idx
            for idx, (start, end) in enumerate(spans)
            if start < match.end and end > match.start
        ]
        if len(affected_indexes) < 2:
            continue
        if len(match.raw) != len(match.replacement):
            continue

        replacement_offset = 0
        for seq, idx in enumerate(affected_indexes):
            start, end = spans[idx]
            overlap_start = max(start, match.start)
            overlap_end = min(end, match.end)
            if overlap_start >= overlap_end:
                continue
            local_start = overlap_start - start
            local_end = overlap_end - start
            slice_len = overlap_end - overlap_start
            before = text_nodes[idx].text or ""
            replacement_chunk = match.replacement[replacement_offset : replacement_offset + slice_len]
            replacement_offset += slice_len
            after = before[:local_start] + replacement_chunk + before[local_end:]
            if after == before:
                continue
            text_nodes[idx].text = after
            replacements.append(
                Replacement(
                    part=part_name,
                    paragraph_index_in_part=paragraph_index,
                    container_id=container_id,
                    node_index_in_paragraph=idx + 1,
                    before=before,
                    after=after,
                    changed_matches=(
                        [{"raw": match.raw, "replacement": match.replacement}]
                        if seq == 0
                        else []
                    ),
                )
            )
    return replacements


def process_docx(src: Path, out: Optional[Path]) -> Dict[str, object]:
    xml_targets = {
        "word/document.xml",
        "word/footnotes.xml",
        "word/endnotes.xml",
        "word/comments.xml",
    }
    prefixes = ("word/header", "word/footer")

    summary = {
        "input": str(src),
        "output": str(out) if out else "",
        "files_changed": 0,
        "nodes_changed": 0,
        "match_replacements": 0,
        "replacements": [],
    }

    zip_sink = None
    zin = zipfile.ZipFile(src, "r")
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        zip_sink = zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED)

    try:
        for info in zin.infolist():
            data = zin.read(info.filename)
            should_process = info.filename in xml_targets or any(
                info.filename.startswith(prefix) and info.filename.endswith(".xml")
                for prefix in prefixes
            )
            if not should_process:
                if zip_sink is not None:
                    zip_sink.writestr(info, data)
                continue

            root = xml_doc_from_bytes(data)
            local_replacements: List[Replacement] = []
            for paragraph_index, container_id, para in iter_paragraphs_for_part(info.filename, root):
                text_nodes = para.xpath(".//w:t", namespaces=NS)
                for node_index, node in enumerate(text_nodes, 1):
                    before = node.text or ""
                    after, changed_matches = normalize_text_node(before)
                    if after == before:
                        continue
                    node.text = after
                    local_replacements.append(
                        Replacement(
                            part=info.filename,
                            paragraph_index_in_part=paragraph_index,
                            container_id=container_id,
                            node_index_in_paragraph=node_index,
                            before=before,
                            after=after,
                            changed_matches=changed_matches,
                        )
                    )
                local_replacements.extend(
                    apply_cross_node_matches(
                        text_nodes,
                        part_name=info.filename,
                        paragraph_index=paragraph_index,
                        container_id=container_id,
                    )
                )

            if local_replacements:
                summary["files_changed"] += 1
                summary["nodes_changed"] += len(local_replacements)
                summary["match_replacements"] += sum(len(item.changed_matches) for item in local_replacements)
                summary["replacements"].extend(asdict(item) for item in local_replacements)

            encoded = xml_to_bytes(root)
            if zip_sink is not None:
                zip_sink.writestr(info, encoded)
    finally:
        zin.close()
        if zip_sink is not None:
            zip_sink.close()

    return summary


def write_report_md(path: Path, summary: Dict[str, object]) -> None:
    lines = ["# DOCX Scripture Reference Normalizer\n\n"]
    lines.append(f"Input: `{summary['input']}`\n\n")
    if summary.get("output"):
        lines.append(f"Output: `{summary['output']}`\n\n")
    lines.append(f"- files changed: {summary['files_changed']}\n")
    lines.append(f"- text nodes changed: {summary['nodes_changed']}\n")
    lines.append(f"- reference replacements: {summary['match_replacements']}\n")
    lines.append("\n## Replacements\n\n")
    for item in summary["replacements"][:200]:
        lines.append(
            f"- `{item['part']}` paragraph #{item['paragraph_index_in_part']}"
            f" node #{item['node_index_in_paragraph']}\n"
            f"  - before: `{item['before']}`\n"
            f"  - after: `{item['after']}`\n"
        )
    hidden = len(summary["replacements"]) - min(200, len(summary["replacements"]))
    if hidden > 0:
        lines.append(f"- ... {hidden} more replacements omitted\n")
    path.write_text("".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalize scripture reference formatting inside DOCX")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="scan a DOCX and report what would change")
    p_scan.add_argument("input")
    p_scan.add_argument("--report-json")
    p_scan.add_argument("--report-md")

    p_norm = sub.add_parser("normalize", help="rewrite scripture references inside a DOCX")
    p_norm.add_argument("input")
    p_norm.add_argument("output")
    p_norm.add_argument("--report-json")
    p_norm.add_argument("--report-md")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    src, temp_dir = resolve_docx(Path(args.input))
    try:
        output = Path(args.output) if args.command == "normalize" else None
        summary = process_docx(src, output)
        if args.report_json:
            Path(args.report_json).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.report_md:
            write_report_md(Path(args.report_md), summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        cleanup_temp(temp_dir)


if __name__ == "__main__":
    raise SystemExit(main())
