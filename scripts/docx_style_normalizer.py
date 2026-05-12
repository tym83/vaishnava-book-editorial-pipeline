#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""
Normalize DOCX styles to the project's canonical Word/InDesign style set.

v1 scope:
- create missing canonical paragraph and character styles
- map common built-in styles to canonical ones
- assign H1 from TOC titles when possible
- convert manual italic/bold to character styles
- make default/unstyled body paragraphs explicit as "Основной текст"
- leave footnote/endnote paragraph semantics to docx_footnote_classifier.py

Examples:
  python3 docx_style_normalizer.py normalize in.docx out.docx
  python3 docx_style_normalizer.py normalize in.docx out.docx --toc-marker "Содержание"
"""

from __future__ import annotations

import argparse
import copy
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from lxml import etree


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
W = f"{{{W_NS}}}"

CANONICAL_PARAGRAPH_STYLES = [
    "Заголовок 1",
    "Заголовок 2",
    "Заголовок 3",
    "Заголовок 4",
    "Шлока",
    "Перевод шлоки",
    "Цитата 1",
    "Цитата 2",
    "Шлока в цитате",
    "Письмо",
    "Источник",
    "Подпись к иллюстрации",
    "Сноска",
    "Список нумерованный 1",
    "Список нумерованный 2",
    "Список ненумерованный 1",
    "Список ненумерованный 2",
    "Основной текст",
]

CANONICAL_CHARACTER_STYLES = [
    "Char Курсив",
    "Char Полужирный",
]

DEFAULT_STYLE_NAME_MAP = {
    "normal": "Основной текст",
    "normal (web)": "Основной текст",
    "no spacing": "Основной текст",
    "текст": "Основной текст",
    "body text": "Основной текст",
    "без интервала1": "Основной текст",
    "heading 1": "Заголовок 1",
    "heading 2": "Заголовок 2",
    "heading 3": "Заголовок 3",
    "heading 4": "Заголовок 4",
    "footnote text": "Сноска",
    "endnote text": "Сноска",
    "sloka": "Шлока",
    "шлока санскрит": "Шлока",
    "шлока перевод": "Перевод шлоки",
}

DEFAULT_CHARACTER_STYLE_NAME_MAP = {
    "emphasis": "Char Курсив",
    "strong": "Char Полужирный",
}

DEFAULT_TOC_MARKERS = ["Содержание", "Contents", "Оглавление"]


@dataclass
class TocEntry:
    title: str
    style_name: Optional[str]
    level: int


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = " ".join(text.strip().split())
    text = text.replace("ё", "е").replace("Ё", "Е")
    return text.casefold()


def clean_text(text: str) -> str:
    return " ".join(text.strip().split())


def convert_doc_to_docx(path: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="docx-style-normalizer-"))
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
        die("docx_style_normalizer currently supports .docx and .doc")
    return path, None


def cleanup_temp(temp_dir: Optional[Path]) -> None:
    if temp_dir and temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)


def local_name(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def visible_text(node) -> str:
    return "".join(t.text or "" for t in node.xpath(".//w:t", namespaces=NS)).strip()


def is_title_candidate(text: str, max_len: int = 120) -> bool:
    text = clean_text(text)
    if not text:
        return False
    if len(text) > max_len:
        return False
    if len(text.split()) > 14:
        return False
    if text.endswith((".", "!", "?", ":", ";", ",")):
        return False
    return True


def merge_title_lines(lines: Sequence[str]) -> List[str]:
    merged: List[str] = []
    for raw in lines:
        line = clean_text(raw)
        if not line:
            continue
        if merged and line[:1].islower() and len(merged[-1]) + 1 + len(line) <= 180:
            merged[-1] = f"{merged[-1]} {line}"
        else:
            merged.append(line)
    return merged


def dedupe_preserve_order(lines: Sequence[str]) -> List[str]:
    seen = set()
    out = []
    for line in lines:
        norm = normalize_text(line)
        if norm in seen:
            continue
        seen.add(norm)
        out.append(line)
    return out


def strip_toc_page_suffix(text: str) -> str:
    text = clean_text(text)
    text = re.sub(r"\s*[0-9ivxlcdm]+$", "", text, flags=re.IGNORECASE).strip()
    return text


class StyleCatalog:
    def __init__(self, root):
        self.root = root
        self.by_id: Dict[str, etree._Element] = {}
        self.by_name: Dict[str, etree._Element] = {}
        self.by_name_norm: Dict[str, etree._Element] = {}
        self.default_by_type: Dict[str, etree._Element] = {}
        self.first_by_type: Dict[str, etree._Element] = {}
        self._rebuild()

    def _rebuild(self) -> None:
        self.by_id.clear()
        self.by_name.clear()
        self.by_name_norm.clear()
        self.default_by_type.clear()
        self.first_by_type.clear()
        for style in self.root.xpath(".//w:style", namespaces=NS):
            style_id = style.get(f"{W}styleId")
            style_type = style.get(f"{W}type") or "unknown"
            name_node = style.find("w:name", namespaces=NS)
            name = name_node.get(f"{W}val") if name_node is not None else style_id
            if style_id:
                self.by_id[style_id] = style
            if name:
                self.by_name[name] = style
                self.by_name_norm.setdefault(normalize_text(name), style)
            self.first_by_type.setdefault(style_type, style)
            if style.get(f"{W}default") in {"1", "true", "True"} and style_type not in self.default_by_type:
                self.default_by_type[style_type] = style

    def by_style_name(self, name: Optional[str]):
        if not name:
            return None
        exact = self.by_name.get(name)
        if exact is not None:
            return exact
        return self.by_name_norm.get(normalize_text(name))

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

    def _unique_style_id(self, style_type: str, base: str) -> str:
        prefix = "P" if style_type == "paragraph" else "C"
        stem = "".join(ch for ch in base if ch.isalnum())[:16] or "Style"
        candidate = f"{prefix}_{stem}"
        idx = 1
        while candidate in self.by_id:
            idx += 1
            candidate = f"{prefix}_{stem}_{idx}"
        return candidate

    def _ensure_name_node(self, style, name: str) -> None:
        node = style.find("w:name", namespaces=NS)
        if node is None:
            node = etree.Element(f"{W}name")
            style.insert(0, node)
        node.set(f"{W}val", name)

    def _ensure_rpr(self, style):
        rpr = style.find("w:rPr", namespaces=NS)
        if rpr is None:
            rpr = etree.Element(f"{W}rPr")
            style.append(rpr)
        return rpr

    def ensure_style(self, target_name: str, style_type: str, base_name: Optional[str] = None) -> str:
        existing = self.by_style_name(target_name)
        if existing is not None:
            return existing.get(f"{W}styleId")

        base = self.by_style_name(base_name) if base_name else None
        if base is None:
            base = self.default_by_type.get(style_type)
        if base is None:
            base = self.first_by_type.get(style_type)
        if base is None:
            die(f"No base style available to create {target_name}")

        style = copy.deepcopy(base)
        style_id = self._unique_style_id(style_type, target_name)
        style.set(f"{W}styleId", style_id)
        style.set(f"{W}type", style_type)
        style.attrib.pop(f"{W}default", None)
        style.set(f"{W}customStyle", "1")
        self._ensure_name_node(style, target_name)

        # Normalize known character style semantics.
        if style_type == "character":
            rpr = self._ensure_rpr(style)
            if target_name == "Char Курсив":
                for tag in ("i", "iCs"):
                    if rpr.find(f"w:{tag}", namespaces=NS) is None:
                        rpr.append(etree.Element(f"{W}{tag}"))
                for tag in ("b", "bCs"):
                    node = rpr.find(f"w:{tag}", namespaces=NS)
                    if node is not None:
                        rpr.remove(node)
            elif target_name == "Char Полужирный":
                for tag in ("b", "bCs"):
                    if rpr.find(f"w:{tag}", namespaces=NS) is None:
                        rpr.append(etree.Element(f"{W}{tag}"))
                for tag in ("i", "iCs"):
                    node = rpr.find(f"w:{tag}", namespaces=NS)
                    if node is not None:
                        rpr.remove(node)

        self.root.append(style)
        self._rebuild()
        return style_id


def ensure_child(parent, tag_name: str):
    node = parent.find(f"w:{tag_name}", namespaces=NS)
    if node is None:
        node = etree.Element(f"{W}{tag_name}")
        parent.append(node)
    return node


def ensure_first_child(parent, tag_name: str):
    node = parent.find(f"w:{tag_name}", namespaces=NS)
    if node is None:
        node = etree.Element(f"{W}{tag_name}")
        parent.insert(0, node)
    return node


def remove_children(parent, tag_names: Sequence[str]) -> None:
    for tag_name in tag_names:
        for node in parent.findall(f"w:{tag_name}", namespaces=NS):
            parent.remove(node)


def load_styles_root(z: zipfile.ZipFile):
    try:
        return etree.fromstring(z.read("word/styles.xml"))
    except KeyError:
        die("word/styles.xml not found in docx")


def iter_story_part_names(z: zipfile.ZipFile) -> List[str]:
    names = []
    for name in z.namelist():
        if name == "word/document.xml":
            names.append(name)
        elif name in {"word/footnotes.xml", "word/endnotes.xml", "word/comments.xml"}:
            names.append(name)
        elif (name.startswith("word/header") or name.startswith("word/footer")) and name.endswith(".xml"):
            names.append(name)
    return names


def iter_paragraphs_for_part(part_name: str, root) -> List[etree._Element]:
    if part_name == "word/document.xml":
        return root.xpath(".//w:body//w:p", namespaces=NS)
    if part_name == "word/footnotes.xml":
        return root.xpath(".//w:footnote[not(@w:type)]//w:p", namespaces=NS)
    if part_name == "word/endnotes.xml":
        return root.xpath(".//w:endnote[not(@w:type)]//w:p", namespaces=NS)
    return root.xpath(".//w:p", namespaces=NS)


def is_note_part(part_name: str) -> bool:
    return part_name in {"word/footnotes.xml", "word/endnotes.xml"}


def get_paragraph_style_name(p, catalog: StyleCatalog, default_name: Optional[str]) -> Optional[str]:
    p_style = p.find("w:pPr/w:pStyle", namespaces=NS)
    if p_style is None:
        return default_name
    return catalog.style_name(p_style.get(f"{W}val"))


def get_run_style_name(r, catalog: StyleCatalog, default_name: Optional[str]) -> Optional[str]:
    r_style = r.find("w:rPr/w:rStyle", namespaces=NS)
    if r_style is None:
        return default_name
    return catalog.style_name(r_style.get(f"{W}val"))


def onoff_is_true(node) -> bool:
    val = node.get(f"{W}val")
    if val is None:
        return True
    return val not in {"0", "false", "False", "off"}


def extract_toc_entries_from_doc_root(
    root,
    catalog: StyleCatalog,
    toc_markers: Sequence[str],
    default_paragraph_name: Optional[str],
    max_len: int = 120,
) -> Tuple[List[TocEntry], Optional[int]]:
    paragraphs = root.xpath(".//w:body//w:p", namespaces=NS)
    markers = {normalize_text(m) for m in toc_markers}
    start = None
    for idx, p in enumerate(paragraphs):
        if normalize_text(visible_text(p)) in markers:
            start = idx + 1
            break
    if start is None:
        return [], None

    raw_entries: List[Tuple[str, Optional[str]]] = []
    stop = None
    collecting = False
    for idx in range(start, len(paragraphs)):
        text = strip_toc_page_suffix(visible_text(paragraphs[idx]))
        style_name = get_paragraph_style_name(paragraphs[idx], catalog, default_paragraph_name)
        if not collecting:
            if is_title_candidate(text, max_len=max_len):
                collecting = True
                raw_entries.append((text, style_name))
                continue
            continue

        if is_title_candidate(text, max_len=max_len):
            raw_entries.append((text, style_name))
            continue

        stop = idx
        break

    merged: List[Tuple[str, Optional[str]]] = []
    for text, style_name in raw_entries:
        if (
            merged
            and text[:1].islower()
            and len(merged[-1][0]) + 1 + len(text) <= 180
        ):
            prev_text, prev_style = merged[-1]
            merged[-1] = (f"{prev_text} {text}", prev_style)
        else:
            merged.append((text, style_name))

    entries: List[TocEntry] = []
    seen = set()
    seen_h1 = False
    for text, style_name in merged:
        norm = normalize_text(text)
        if norm in seen:
            continue
        seen.add(norm)
        style_norm = normalize_text(style_name or "")
        if text.startswith(("Часть", "Глава")):
            level = 1
        elif style_norm in {"toc 1", "toc 2"}:
            level = 1
        elif style_norm == "toc 3":
            level = 2 if seen_h1 else 1
        else:
            level = 1
        if level == 1:
            seen_h1 = True
        entries.append(TocEntry(title=text, style_name=style_name, level=level))
    return entries, stop


def assign_headings_from_toc(
    root,
    catalog: StyleCatalog,
    canonical_ids: Dict[str, str],
    default_paragraph_name: Optional[str],
    toc_markers: Sequence[str],
) -> Dict[str, int]:
    entries, stop_idx = extract_toc_entries_from_doc_root(
        root,
        catalog,
        toc_markers,
        default_paragraph_name=default_paragraph_name,
    )
    if not entries:
        return {"Заголовок 1": 0, "Заголовок 2": 0, "Заголовок 3": 0, "Заголовок 4": 0}

    paragraphs = root.xpath(".//w:body//w:p", namespaces=NS)
    search_pos = stop_idx or 0
    assignments = {"Заголовок 1": 0, "Заголовок 2": 0, "Заголовок 3": 0, "Заголовок 4": 0}
    for entry in entries:
        target = normalize_text(entry.title)
        found_idx = None
        for idx in range(search_pos, len(paragraphs)):
            if normalize_text(strip_toc_page_suffix(visible_text(paragraphs[idx]))) == target:
                found_idx = idx
                break
        if found_idx is None:
            continue
        p = paragraphs[found_idx]
        ppr = ensure_first_child(p, "pPr")
        pstyle = ensure_first_child(ppr, "pStyle")
        target_name = {
            1: "Заголовок 1",
            2: "Заголовок 2",
            3: "Заголовок 3",
            4: "Заголовок 4",
        }.get(entry.level, "Заголовок 1")
        target_style_id = canonical_ids[target_name]
        if pstyle.get(f"{W}val") != target_style_id:
            pstyle.set(f"{W}val", target_style_id)
            assignments[target_name] += 1
        search_pos = found_idx + 1
    return assignments


def ensure_canonical_styles(catalog: StyleCatalog) -> Dict[str, str]:
    style_ids: Dict[str, str] = {}
    base_map = {
        "Заголовок 1": "heading 1",
        "Заголовок 2": "heading 2",
        "Заголовок 3": "heading 3",
        "Заголовок 4": "heading 4",
        "Сноска": "footnote text",
        "Char Курсив": "Default Paragraph Font",
        "Char Полужирный": "Default Paragraph Font",
    }
    for name in CANONICAL_PARAGRAPH_STYLES:
        style_ids[name] = catalog.ensure_style(name, "paragraph", base_name=base_map.get(name))
    for name in CANONICAL_CHARACTER_STYLES:
        style_ids[name] = catalog.ensure_style(name, "character", base_name=base_map.get(name))
    return style_ids


def build_style_map(extra_maps: Sequence[str]) -> Dict[str, str]:
    mapping = dict(DEFAULT_STYLE_NAME_MAP)
    for item in extra_maps:
        if "=" not in item:
            die(f"Bad --map value: {item}. Expected source=target")
        src, dst = item.split("=", 1)
        src = src.strip()
        dst = dst.strip()
        if not src or not dst:
            die(f"Bad --map value: {item}. Expected source=target")
        mapping[normalize_text(src)] = dst
    return mapping


def build_character_style_map() -> Dict[str, str]:
    return dict(DEFAULT_CHARACTER_STYLE_NAME_MAP)


def normalize_docx(src: Path, out: Path, toc_markers: Sequence[str], extra_maps: Sequence[str]) -> dict:
    style_map = build_style_map(extra_maps)
    char_style_map = build_character_style_map()

    with zipfile.ZipFile(src, "r") as zin:
        styles_root = load_styles_root(zin)
        catalog = StyleCatalog(styles_root)
        default_paragraph_name = catalog.default_style_name("paragraph")
        default_character_name = catalog.default_style_name("character")
        canonical_ids = ensure_canonical_styles(catalog)

        part_roots: Dict[str, etree._Element] = {}
        for name in iter_story_part_names(zin):
            try:
                part_roots[name] = etree.fromstring(zin.read(name))
            except etree.XMLSyntaxError:
                continue

        toc_heading_assignments = {"Заголовок 1": 0, "Заголовок 2": 0, "Заголовок 3": 0, "Заголовок 4": 0}
        document_root = part_roots.get("word/document.xml")
        if document_root is not None:
            toc_heading_assignments = assign_headings_from_toc(
                document_root,
                catalog,
                canonical_ids,
                default_paragraph_name=default_paragraph_name,
                toc_markers=toc_markers,
            )

        remapped_paragraphs = 0
        remapped_runs = 0
        converted_manual_italic = 0
        converted_manual_bold = 0
        skipped_combined_emphasis = 0
        preserved_note_paragraph_styles = 0

        for part_name, root in part_roots.items():
            for p in iter_paragraphs_for_part(part_name, root):
                current_name = get_paragraph_style_name(p, catalog, default_paragraph_name)
                target_name = None
                if is_note_part(part_name):
                    # Footnotes in Vaibhava use several semantic note types, often all
                    # hidden behind No Spacing/footnote text. Do not collapse them to
                    # body text here; docx_footnote_classifier owns that decision.
                    preserved_note_paragraph_styles += 1
                else:
                    target_name = style_map.get(normalize_text(current_name or ""))
                if target_name:
                    target_id = canonical_ids.get(target_name)
                    if target_id:
                        ppr = ensure_first_child(p, "pPr")
                        pstyle = ensure_first_child(ppr, "pStyle")
                        if pstyle.get(f"{W}val") != target_id:
                            pstyle.set(f"{W}val", target_id)
                            remapped_paragraphs += 1

                for r in p.xpath("./descendant::w:r", namespaces=NS):
                    rpr = r.find("w:rPr", namespaces=NS)
                    if rpr is None:
                        continue

                    current_char_name = get_run_style_name(r, catalog, default_character_name)
                    explicit_char_target = char_style_map.get(normalize_text(current_char_name or ""))
                    defaultish = current_char_name in {None, default_character_name, "Default Paragraph Font"}
                    italic = any(
                        (node := rpr.find(f"w:{tag}", namespaces=NS)) is not None and onoff_is_true(node)
                        for tag in ("i", "iCs")
                    )
                    bold = any(
                        (node := rpr.find(f"w:{tag}", namespaces=NS)) is not None and onoff_is_true(node)
                        for tag in ("b", "bCs")
                    )

                    target_char_name = None
                    if explicit_char_target:
                        target_char_name = explicit_char_target
                    elif defaultish:
                        if italic and not bold:
                            target_char_name = "Char Курсив"
                        elif bold and not italic:
                            target_char_name = "Char Полужирный"
                        elif bold and italic:
                            skipped_combined_emphasis += 1

                    if target_char_name:
                        rstyle = ensure_first_child(rpr, "rStyle")
                        target_id = canonical_ids[target_char_name]
                        if rstyle.get(f"{W}val") != target_id:
                            rstyle.set(f"{W}val", target_id)
                            remapped_runs += 1
                        if target_char_name == "Char Курсив":
                            remove_children(rpr, ["i", "iCs"])
                            converted_manual_italic += 1
                        elif target_char_name == "Char Полужирный":
                            remove_children(rpr, ["b", "bCs"])
                            converted_manual_bold += 1

        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(src, "r") as zin, zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                data = zin.read(info.filename)
                if info.filename == "word/styles.xml":
                    zout.writestr(info, etree.tostring(styles_root, xml_declaration=True, encoding="UTF-8", standalone="yes"))
                elif info.filename in part_roots:
                    root = part_roots[info.filename]
                    zout.writestr(info, etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone="yes"))
                else:
                    zout.writestr(info, data)

    return {
        "input": str(src),
        "output": str(out),
        "toc_heading_assignments": toc_heading_assignments,
        "remapped_paragraphs": remapped_paragraphs,
        "remapped_runs": remapped_runs,
        "converted_manual_italic": converted_manual_italic,
        "converted_manual_bold": converted_manual_bold,
        "skipped_combined_emphasis": skipped_combined_emphasis,
        "preserved_note_paragraph_styles": preserved_note_paragraph_styles,
        "created_styles": list(canonical_ids.keys()),
    }


def cmd_normalize(args) -> None:
    src, temp_dir = resolve_source(Path(args.input))
    out = Path(args.output)
    try:
        summary = normalize_docx(src, out, toc_markers=args.toc_marker, extra_maps=args.map)
        print(f"Normalized styles: {summary['input']} -> {summary['output']}")
        print(f"TOC heading assignments: {summary['toc_heading_assignments']}")
        print(f"Paragraph remaps: {summary['remapped_paragraphs']}")
        print(f"Run remaps: {summary['remapped_runs']}")
        print(f"Manual italic -> Char Курсив: {summary['converted_manual_italic']}")
        print(f"Manual bold -> Char Полужирный: {summary['converted_manual_bold']}")
        print(f"Skipped combined bold+italic runs: {summary['skipped_combined_emphasis']}")
        print(f"Preserved note paragraph styles: {summary['preserved_note_paragraph_styles']}")
    finally:
        cleanup_temp(temp_dir)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Normalize DOCX styles to canonical project styles")
    sub = p.add_subparsers(dest="cmd", required=True)

    norm = sub.add_parser("normalize")
    norm.add_argument("input")
    norm.add_argument("output")
    norm.add_argument("--map", action="append", default=[], help="Extra source=target style mapping")
    norm.add_argument(
        "--toc-marker",
        action="append",
        default=list(DEFAULT_TOC_MARKERS),
        help="Possible TOC marker lines for H1 assignment",
    )
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
