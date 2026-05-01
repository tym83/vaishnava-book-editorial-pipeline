#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Resolve scripture references against the local Vedabase mirror."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from lxml import etree

from text_structure import (
    NS,
    W,
    cleanup_temp,
    extract_vedabase_html_document,
    find_vedabase_root,
    first_xpath_text,
    load_html_tree,
    normalize_source,
    normalize_vedabase_web_path,
    vedabase_html_path_from_web_path,
    visible_text,
)


RANGE_SEP_PATTERN = re.compile(r"\s*[-–—]\s*")
BG_PATTERN = re.compile(
    r"(?P<raw>\b(?:бг|bg)\.?\s*(?P<chapter>\d+)\s*\.\s*(?P<verse>\d+(?:\s*[-–—]\s*\d+)?))",
    flags=re.IGNORECASE,
)
SB_PATTERN = re.compile(
    r"(?P<raw>\b(?:шб|sb)\.?\s*(?P<canto>\d+)\s*\.\s*(?P<chapter>\d+)\s*\.\s*(?P<verse>\d+(?:\s*[-–—]\s*\d+)?))",
    flags=re.IGNORECASE,
)
CC_PATTERN = re.compile(
    r"(?P<raw>\b(?:чч|cc)\.?\s*(?P<lila>[A-Za-zА-Яа-яЁё\-]+\s*[A-Za-zА-Яа-яЁё\-]*)\s*(?P<chapter>\d+)\s*\.\s*(?P<verse>\d+(?:\s*[-–—]\s*\d+)?))",
    flags=re.IGNORECASE,
)
ISO_PATTERN = re.compile(
    r"(?P<raw>\b(?:ишо|ишопанишад|iso|isopanisad)\.?\s*(?P<verse>\d+(?:\s*[-–—]\s*\d+)?))",
    flags=re.IGNORECASE,
)

LILA_ALIASES = {
    "adi": "adi",
    "adilila": "adi",
    "ади": "adi",
    "адилила": "adi",
    "madhya": "madhya",
    "madhyalila": "madhya",
    "мадхья": "madhya",
    "мадхьялила": "madhya",
    "мадхйа": "madhya",
    "мадхйалила": "madhya",
    "antya": "antya",
    "antyalila": "antya",
    "антья": "antya",
    "антьялила": "antya",
    "антйа": "antya",
    "антйалила": "antya",
}


@dataclass
class ReferenceHit:
    raw_text: str
    normalized_ref: str
    canonical_display: str
    replacement_text: str
    needs_normalization: bool
    work_id: str
    path_parts: List[str]
    block_index: int
    block_locator: str
    block_part: str
    block_section: str
    block_excerpt: str
    source_locator: Optional[str]
    verse_id: Optional[str]
    paragraph_index_in_part: Optional[int]
    container_id: Optional[str]
    match_span: Tuple[int, int]


def stable_token(text: str) -> str:
    return re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "", (text or "").casefold())


def normalize_range_token(token: str) -> str:
    return RANGE_SEP_PATTERN.sub("-", (token or "").strip())


def normalize_reference_display(text: str) -> str:
    return " ".join((text or "").replace("\u00a0", " ").strip().split())


def excerpt(text: str, limit: int = 160) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def section_map(document) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    for block in document.blocks:
        sections.setdefault(block.section, []).append(block.text)
    return sections


def normalize_lila_token(token: str) -> Optional[str]:
    return LILA_ALIASES.get(stable_token(token))


def lila_display_ru(token: str) -> str:
    if token == "adi":
        return "Ади"
    if token == "madhya":
        return "Мадхья"
    if token == "antya":
        return "Антья"
    return token


def format_reference_display(work_id: str, path_parts: Sequence[str], *, nbsp: bool) -> str:
    sep = "\u00a0" if nbsp else " "
    if work_id == "bg" and len(path_parts) >= 3:
        return f"БГ{sep}{path_parts[1]}.{path_parts[2]}"
    if work_id == "sb" and len(path_parts) >= 4:
        return f"ШБ{sep}{path_parts[1]}.{path_parts[2]}.{path_parts[3]}"
    if work_id.startswith("cc/") and len(path_parts) >= 4:
        return f"ЧЧ{sep}{lila_display_ru(path_parts[1])}{sep}{path_parts[2]}.{path_parts[3]}"
    if work_id == "iso" and len(path_parts) >= 2:
        return f"Ишо{sep}{path_parts[1]}"
    return sep.join(path_parts)


def build_reference_hit(
    *,
    raw_text: str,
    normalized_ref: str,
    work_id: str,
    path_parts: List[str],
    block: Dict[str, object],
    match_span: Tuple[int, int],
) -> ReferenceHit:
    canonical_display = format_reference_display(work_id, path_parts, nbsp=False)
    replacement_text = format_reference_display(work_id, path_parts, nbsp=True)
    normalized_raw = normalize_reference_display(raw_text)
    return ReferenceHit(
        raw_text=raw_text,
        normalized_ref=normalized_ref,
        canonical_display=canonical_display,
        replacement_text=replacement_text,
        needs_normalization=(normalized_raw != canonical_display),
        work_id=work_id,
        path_parts=path_parts,
        block_index=int(block.get("index") or 0),
        block_locator=str(block.get("locator") or f"block:{block.get('index') or 0}"),
        block_part=str(block.get("part") or ""),
        block_section=str(block.get("section") or "body"),
        block_excerpt=excerpt(str(block.get("text") or "")),
        source_locator=(str(block.get("source_locator")) if block.get("source_locator") else None),
        verse_id=(str(block.get("verse_id")) if block.get("verse_id") else None),
        paragraph_index_in_part=(int(block.get("paragraph_index_in_part")) if block.get("paragraph_index_in_part") else None),
        container_id=(str(block.get("container_id")) if block.get("container_id") else None),
        match_span=match_span,
    )


def extract_references_from_text(text: str, block: Dict[str, object]) -> List[ReferenceHit]:
    hits: List[ReferenceHit] = []

    for match in BG_PATTERN.finditer(text):
        chapter = match.group("chapter")
        verse = normalize_range_token(match.group("verse"))
        hits.append(
            build_reference_hit(
                raw_text=match.group("raw"),
                normalized_ref=f"BG {chapter}.{verse}",
                work_id="bg",
                path_parts=["bg", chapter, verse],
                block=block,
                match_span=match.span(),
            )
        )

    for match in SB_PATTERN.finditer(text):
        canto = match.group("canto")
        chapter = match.group("chapter")
        verse = normalize_range_token(match.group("verse"))
        hits.append(
            build_reference_hit(
                raw_text=match.group("raw"),
                normalized_ref=f"SB {canto}.{chapter}.{verse}",
                work_id="sb",
                path_parts=["sb", canto, chapter, verse],
                block=block,
                match_span=match.span(),
            )
        )

    for match in CC_PATTERN.finditer(text):
        lila = normalize_lila_token(match.group("lila"))
        if not lila:
            continue
        chapter = match.group("chapter")
        verse = normalize_range_token(match.group("verse"))
        hits.append(
            build_reference_hit(
                raw_text=match.group("raw"),
                normalized_ref=f"CC {lila.title()} {chapter}.{verse}",
                work_id=f"cc/{lila}",
                path_parts=["cc", lila, chapter, verse],
                block=block,
                match_span=match.span(),
            )
        )

    for match in ISO_PATTERN.finditer(text):
        verse = normalize_range_token(match.group("verse"))
        hits.append(
            build_reference_hit(
                raw_text=match.group("raw"),
                normalized_ref=f"ISO {verse}",
                work_id="iso",
                path_parts=["iso", verse],
                block=block,
                match_span=match.span(),
            )
        )

    hits.sort(key=lambda item: (item.match_span[0], item.match_span[1]))
    return hits


def reference_web_path(reference: ReferenceHit, locale: str) -> str:
    return normalize_vedabase_web_path("/" + "/".join([locale, "library"] + reference.path_parts))


def reference_sections_payload(document, include_sections: bool) -> Dict[str, object]:
    payload = {
        "section_counts": dict(document.metadata.get("section_counts", {})),
        "kind_counts": dict(document.metadata.get("kind_counts", {})),
    }
    if include_sections:
        payload["sections"] = section_map(document)
    return payload


def resolve_reference_hit(
    reference: ReferenceHit,
    vedabase_root: Path,
    *,
    locale: str = "ru",
    include_sections: bool = False,
) -> Dict[str, object]:
    web_path = reference_web_path(reference, locale=locale)
    html_path = vedabase_html_path_from_web_path(vedabase_root, web_path)
    result = asdict(reference)
    result["web_path"] = web_path
    result["html_path"] = str(html_path)
    result["locale"] = locale
    result["resolved"] = html_path.exists()

    if not html_path.exists():
        return result

    document = extract_vedabase_html_document(html_path)
    _raw, doc = load_html_tree(html_path)
    result["title"] = first_xpath_text(doc, "//title[1]")
    result["h1"] = first_xpath_text(doc, "//h1[1]")
    result.update(reference_sections_payload(document, include_sections=include_sections))
    return result


def xml_doc_from_bytes(data: bytes):
    parser = etree.XMLParser(remove_blank_text=False, recover=True)
    return etree.fromstring(data, parser=parser)


def iter_docx_blocks(path: Path) -> List[Dict[str, object]]:
    blocks: List[Dict[str, object]] = []

    def append_block(
        text: str,
        *,
        locator: str,
        part: str,
        paragraph_index_in_part: int,
        section: str = "body",
        source_locator: Optional[str] = None,
        container_id: Optional[str] = None,
    ) -> None:
        normalized = " ".join((text or "").split())
        if not normalized:
            return
        blocks.append(
            {
                "index": len(blocks) + 1,
                "locator": locator,
                "part": part,
                "section": section,
                "text": normalized,
                "source_locator": source_locator,
                "paragraph_index_in_part": paragraph_index_in_part,
                "container_id": container_id,
            }
        )

    with zipfile.ZipFile(path, "r") as zf:
        body_root = xml_doc_from_bytes(zf.read("word/document.xml"))
        for idx, para in enumerate(body_root.xpath(".//w:body/w:p", namespaces=NS), 1):
            append_block(
                visible_text(para),
                locator=f"body:{idx}",
                part="word/document.xml",
                paragraph_index_in_part=idx,
            )

        if "word/footnotes.xml" in zf.namelist():
            foot_root = xml_doc_from_bytes(zf.read("word/footnotes.xml"))
            paragraph_index = 0
            for footnote in foot_root.xpath(".//w:footnote[not(@w:type)]", namespaces=NS):
                footnote_id = footnote.get(f"{W}id") or "?"
                for idx, para in enumerate(footnote.findall("w:p", namespaces=NS), 1):
                    paragraph_index += 1
                    append_block(
                        visible_text(para),
                        locator=f"footnote:{footnote_id}:{idx}",
                        part="word/footnotes.xml",
                        paragraph_index_in_part=paragraph_index,
                        section="footnote",
                        container_id=str(footnote_id),
                    )

        if "word/endnotes.xml" in zf.namelist():
            end_root = xml_doc_from_bytes(zf.read("word/endnotes.xml"))
            paragraph_index = 0
            for endnote in end_root.xpath(".//w:endnote[not(@w:type)]", namespaces=NS):
                endnote_id = endnote.get(f"{W}id") or "?"
                for idx, para in enumerate(endnote.findall("w:p", namespaces=NS), 1):
                    paragraph_index += 1
                    append_block(
                        visible_text(para),
                        locator=f"endnote:{endnote_id}:{idx}",
                        part="word/endnotes.xml",
                        paragraph_index_in_part=paragraph_index,
                        section="endnote",
                        container_id=str(endnote_id),
                    )

        if "word/comments.xml" in zf.namelist():
            comments_root = xml_doc_from_bytes(zf.read("word/comments.xml"))
            paragraph_index = 0
            for comment in comments_root.xpath(".//w:comment", namespaces=NS):
                comment_id = comment.get(f"{W}id") or "?"
                for idx, para in enumerate(comment.findall("w:p", namespaces=NS), 1):
                    paragraph_index += 1
                    append_block(
                        visible_text(para),
                        locator=f"comment:{comment_id}:{idx}",
                        part="word/comments.xml",
                        paragraph_index_in_part=paragraph_index,
                        section="comment",
                        container_id=str(comment_id),
                    )

    return blocks


def load_blocks_from_json(path: Path) -> List[Dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_blocks = payload.get("blocks") if isinstance(payload, dict) else None
    if not isinstance(raw_blocks, list):
        raise SystemExit(f"ERROR: Unsupported normalized JSON schema: {path}")

    blocks: List[Dict[str, object]] = []
    for raw in raw_blocks:
        if not isinstance(raw, dict):
            continue
        text = " ".join(str(raw.get("text") or "").split())
        if not text:
            continue
        blocks.append(
            {
                "index": int(raw.get("index") or len(blocks) + 1),
                "locator": str(raw.get("source_locator") or raw.get("part") or f"json:{len(blocks) + 1}"),
                "part": str(raw.get("part") or "normalized_json"),
                "section": str(raw.get("section") or "body"),
                "text": text,
                "source_locator": raw.get("source_locator"),
                "verse_id": raw.get("verse_id"),
                "paragraph_index_in_part": raw.get("paragraph_index_in_part"),
                "container_id": raw.get("container_id"),
            }
        )
    return blocks


def load_blocks_generic(path: Path, source_format: str) -> Tuple[List[Dict[str, object]], Optional[Path]]:
    document, temp_dir = normalize_source(path, forced_format=source_format)
    blocks = [
        {
            "index": block.index,
            "locator": block.source_locator or f"{block.part}:{block.index}",
            "part": block.part,
            "section": block.section,
            "text": block.text,
            "source_locator": block.source_locator,
            "verse_id": block.verse_id,
            "paragraph_index_in_part": getattr(block, "paragraph_index_in_part", None),
            "container_id": getattr(block, "container_id", None),
        }
        for block in document.blocks
        if block.text
    ]
    return blocks, temp_dir


def resolve_input_blocks(path: Path) -> Tuple[List[Dict[str, object]], Optional[Path]]:
    if not path.exists():
        raise SystemExit(f"ERROR: Input not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".json":
        return load_blocks_from_json(path), None
    if suffix == ".doc":
        document, temp_dir = normalize_source(path, forced_format="doc")
        return iter_docx_blocks(Path(document.source_path)), temp_dir
    if suffix == ".docx":
        return iter_docx_blocks(path), None
    if suffix in {".txt", ".md"}:
        return load_blocks_generic(path, source_format="text")
    if suffix in {".html", ".htm"}:
        return load_blocks_generic(path, source_format="auto")
    raise SystemExit(f"ERROR: Unsupported input format for reference scan: {path.suffix}")


def scan_input_for_references(
    input_path: Path,
    *,
    vedabase_root: Path,
    locale: str = "ru",
    include_sections: bool = False,
) -> Dict[str, object]:
    blocks, temp_dir = resolve_input_blocks(input_path)
    try:
        hits: List[Dict[str, object]] = []
        for block in blocks:
            for reference in extract_references_from_text(str(block.get("text") or ""), block):
                hits.append(
                    resolve_reference_hit(
                        reference,
                        vedabase_root,
                        locale=locale,
                        include_sections=include_sections,
                    )
                )

        resolved_count = sum(1 for item in hits if item.get("resolved"))
        unresolved_count = len(hits) - resolved_count
        return {
            "input_path": str(input_path),
            "vedabase_root": str(vedabase_root),
            "locale": locale,
            "reference_count": len(hits),
            "resolved_count": resolved_count,
            "unresolved_count": unresolved_count,
            "work_counts": dict(Counter(item["work_id"] for item in hits)),
            "references": hits,
        }
    finally:
        cleanup_temp(temp_dir)


def lookup_reference(
    reference_text: str,
    *,
    vedabase_root: Path,
    locale: str = "ru",
    include_sections: bool = True,
) -> Dict[str, object]:
    block = {
        "index": 1,
        "locator": "lookup:1",
        "part": "lookup",
        "section": "body",
        "text": reference_text,
    }
    hits = extract_references_from_text(reference_text, block)
    if not hits:
        raise SystemExit(f"ERROR: Could not parse scripture reference: {reference_text}")
    if len(hits) > 1:
        raise SystemExit(f"ERROR: Ambiguous scripture reference: {reference_text}")
    return resolve_reference_hit(hits[0], vedabase_root, locale=locale, include_sections=include_sections)


def write_report_md(path: Path, summary: Dict[str, object]) -> None:
    lines = ["# Vedabase Reference Scan\n\n"]
    lines.append(f"Input: `{summary['input_path']}`\n\n")
    lines.append(f"Locale: `{summary['locale']}`\n\n")
    lines.append(f"- references: {summary['reference_count']}\n")
    lines.append(f"- resolved: {summary['resolved_count']}\n")
    lines.append(f"- unresolved: {summary['unresolved_count']}\n")
    lines.append("\n## Hits\n\n")
    for item in summary["references"]:
        status = "resolved" if item.get("resolved") else "unresolved"
        lines.append(
            f"- `{item['normalized_ref']}` [{status}] block #{item['block_index']} `{item['block_locator']}`\n"
            f"  - excerpt: `{item['block_excerpt']}`\n"
        )
        if item.get("resolved"):
            lines.append(f"  - vedabase: `{item['web_path']}`\n")
            if item.get("h1"):
                lines.append(f"  - title: `{item['h1']}`\n")
        else:
            lines.append(f"  - missing: `{item['web_path']}`\n")
    path.write_text("".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve scripture references against a local Vedabase mirror")
    sub = parser.add_subparsers(dest="command", required=True)

    p_lookup = sub.add_parser("lookup", help="resolve one scripture reference")
    p_lookup.add_argument("reference")
    p_lookup.add_argument("--vedabase-root")
    p_lookup.add_argument("--locale", default="ru")
    p_lookup.add_argument("--no-sections", action="store_true", help="omit full section text from the output")

    p_scan = sub.add_parser("scan", help="scan a file for scripture references")
    p_scan.add_argument("input")
    p_scan.add_argument("--vedabase-root")
    p_scan.add_argument("--locale", default="ru")
    p_scan.add_argument("--include-sections", action="store_true")
    p_scan.add_argument("--report-json")
    p_scan.add_argument("--report-md")
    return parser


def resolve_vedabase_root_arg(raw: Optional[str], fallback_input: Optional[Path] = None) -> Path:
    if raw:
        root = Path(raw)
    elif fallback_input is not None:
        root = find_vedabase_root(fallback_input) or Path("/home/tym83/Загрузки/Служение/vedabase")
    else:
        root = Path("/home/tym83/Загрузки/Служение/vedabase")
    if not root.exists():
        raise SystemExit(f"ERROR: Vedabase root not found: {root}")
    return root


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "lookup":
        vedabase_root = resolve_vedabase_root_arg(args.vedabase_root)
        result = lookup_reference(
            args.reference,
            vedabase_root=vedabase_root,
            locale=args.locale,
            include_sections=not args.no_sections,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "scan":
        input_path = Path(args.input)
        vedabase_root = resolve_vedabase_root_arg(args.vedabase_root, fallback_input=input_path)
        summary = scan_input_for_references(
            input_path,
            vedabase_root=vedabase_root,
            locale=args.locale,
            include_sections=args.include_sections,
        )
        if args.report_json:
            Path(args.report_json).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.report_md:
            write_report_md(Path(args.report_md), summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
