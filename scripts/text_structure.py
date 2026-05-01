#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Shared structured text extraction helpers for Vedabase and review scripts."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from xml.etree import ElementTree as ET

from lxml import etree, html as lxml_html


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
W = f"{{{W_NS}}}"

SCRIPTURE_REF_PATTERN = re.compile(
    r"(?i)\b("
    r"шб|бг|чч|ав|гв|сдж|шбут|шпу|SB|Bg|Cc|"
    r"adi|madhya|antya|"
    r"патр|патрāвалӣ|gaudiya"
    r")\b"
)
COMBINING_MARKS = "\u0304\u0323\u0307\u0303\u0301"
VEDABASE_SECTION_CLASSES = {
    "av-bengali": "bengali",
    "av-devanagari": "devanagari",
    "av-verse_text": "verse_text",
    "av-synonyms": "synonyms",
    "av-translation": "translation",
    "av-purport": "purport",
    "av-commentary": "commentary",
}
VEDABASE_IGNORED_BLOCK_TEXTS = {
    "Деванагари",
    "Текст стиха",
    "Пословный перевод",
    "Перевод",
    "Комментарий",
}
VERSE_HEADING_PATTERN = re.compile(r"(?i)^(?:текст(?:ы)?|texts?|verses?)\s+(.+)$")


@dataclass
class StructuredBlock:
    index: int
    part: str
    section: str
    text: str
    style_name: Optional[str]
    kind: str
    word_count: int
    char_count: int
    footnote_refs: int
    digit_signature: str
    has_quote_marks: bool
    translit_score: int
    verse_id: Optional[str] = None
    source_locator: Optional[str] = None


@dataclass
class StructuredDocument:
    version: int
    source_path: str
    source_format: str
    metadata: Dict[str, object]
    blocks: List[StructuredBlock]

    def to_dict(self) -> Dict[str, object]:
        return {
            "version": self.version,
            "source_path": self.source_path,
            "source_format": self.source_format,
            "metadata": self.metadata,
            "blocks": [asdict(block) for block in self.blocks],
        }


@dataclass
class VedabasePathInfo:
    source_path: str
    web_path: str
    locale: str
    library_parts: List[str]
    root_id: str
    work_id: str
    page_type: str
    chapter_number: Optional[str]
    chapter_key: Optional[str]
    chapter_web_path: Optional[str]
    advanced_view_web_path: Optional[str]
    verse_id: Optional[str]
    path_depth: int

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class VedabaseVerse:
    verse_index: int
    verse_id: str
    verse_label: str
    source_path: str
    vedabase_path: str
    source_mode: str
    sections: Dict[str, List[str]]
    blocks: List[StructuredBlock]
    title: Optional[str] = None
    heading_id: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "verse_index": self.verse_index,
            "verse_id": self.verse_id,
            "verse_label": self.verse_label,
            "title": self.title,
            "heading_id": self.heading_id,
            "source_path": self.source_path,
            "vedabase_path": self.vedabase_path,
            "source_mode": self.source_mode,
            "block_count": len(self.blocks),
            "section_counts": {key: len(values) for key, values in self.sections.items()},
            "sections": self.sections,
            "blocks": [asdict(block) for block in self.blocks],
        }


@dataclass
class VedabaseChapter:
    version: int
    source_path: str
    source_format: str
    metadata: Dict[str, object]
    blocks: List[StructuredBlock]
    verses: List[VedabaseVerse]

    def to_dict(self) -> Dict[str, object]:
        return {
            "version": self.version,
            "source_path": self.source_path,
            "source_format": self.source_format,
            "metadata": self.metadata,
            "blocks": [asdict(block) for block in self.blocks],
            "verses": [verse.to_dict() for verse in self.verses],
        }


@dataclass
class VedabaseChapterContext:
    vedabase_root: Path
    chapter_dir: Path
    chapter_page_path: Optional[Path]
    advanced_view_path: Optional[Path]
    chapter_info: VedabasePathInfo


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def clean_text(text: str) -> str:
    return " ".join((text or "").replace("\u00a0", " ").strip().split())


def digit_signature(text: str) -> str:
    nums = re.findall(r"\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?", text)
    return "|".join(nums[:8])


def translit_score(text: str) -> int:
    score = 0
    score += sum(text.count(ch) for ch in COMBINING_MARKS)
    score += len(re.findall(r"[A-Za-zĀāĪīŪūṚṛṜṝḶḷṂṃṄṅÑñṆṇṬṭḌḍḤḥŚśṢṣ]", text))
    score += len(re.findall(r"[А-Яа-яЁё][̣̄̇̃́]", text))
    return score


def looks_like_transliteration_text(text: str) -> bool:
    t = clean_text(text)
    if not t:
        return False
    words = t.split()
    if len(words) > 40 or re.search(r"[.!?]", t):
        return False
    if any(mark in t for mark in COMBINING_MARKS):
        return True
    if re.search(r"[ĀāĪīŪūṚṛṜṝḶḷṂṃṄṅÑñṆṇṬṭḌḍḤḥŚśṢṣ]", t):
        return True
    latin_words = re.findall(r"\b[A-Za-z][A-Za-z-]{2,}\b", t)
    return len(latin_words) >= 3 and len(latin_words) >= max(3, len(words) // 2)


def infer_kind(style_name: Optional[str], text: str) -> str:
    style = (style_name or "").casefold()
    t = clean_text(text)
    if not t:
        return "empty"
    if "заголовок 1" in style or style == "heading 1":
        return "heading1"
    if "заголовок 2" in style or style == "heading 2":
        return "heading2"
    if "заголовок 3" in style or style == "heading 3":
        return "heading3"
    if "заголовок 4" in style or style == "heading 4":
        return "heading4"
    if "шлока в цитате" in style:
        return "quoted_shloka"
    if "шлока" in style and "перевод" not in style:
        return "shloka"
    if "перевод шлоки" in style:
        return "shloka_translation"
    if "цитата 1" in style:
        return "quote1"
    if "цитата 2" in style:
        return "quote2"
    if "письмо" in style:
        return "letter"
    if "источник" in style:
        return "source"
    if "подпись к иллюстрации" in style:
        return "caption"
    if "список нумерованный" in style:
        return "list_numbered"
    if "список ненумерованный" in style:
        return "list_bulleted"
    if "сноска" in style or style in {"footnote text", "footnotetext"}:
        return "footnote"

    words = t.split()
    if len(words) <= 12 and not t.endswith((".", "!", "?", ":", ";", ",")):
        return "heading_like"
    if re.match(r"^\d+[\.\)]\s+", t):
        return "list_numbered"
    if re.match(r"^[\-–—*]\s+", t):
        return "list_bulleted"
    if t.startswith(("«", "\"")) and t.endswith(("»", "\"")) and len(words) <= 120:
        return "quote_like"
    if SCRIPTURE_REF_PATTERN.search(t) and re.search(r"\d", t):
        return "source_like"
    if looks_like_transliteration_text(t):
        return "shloka_like"
    return "body"


def override_kind_for_section(section: str, text: str, current_kind: str) -> str:
    if section == "devanagari":
        return "devanagari"
    if section == "bengali":
        return "bengali"
    if section == "synonyms":
        return "synonyms"
    if section == "verse_text":
        if translit_score(text) >= 2:
            return "transliteration"
        return "verse_text"
    return current_kind


def build_block(
    *,
    index: int,
    part: str,
    section: str,
    text: str,
    style_name: Optional[str] = None,
    footnote_refs: int = 0,
    verse_id: Optional[str] = None,
    source_locator: Optional[str] = None,
) -> StructuredBlock:
    normalized = clean_text(text)
    kind = infer_kind(style_name, normalized)
    kind = override_kind_for_section(section, normalized, kind)
    return StructuredBlock(
        index=index,
        part=part,
        section=section,
        text=normalized,
        style_name=style_name,
        kind=kind,
        word_count=len(normalized.split()),
        char_count=len(normalized),
        footnote_refs=footnote_refs,
        digit_signature=digit_signature(normalized),
        has_quote_marks=("«" in normalized or "»" in normalized or '"' in normalized),
        translit_score=translit_score(normalized),
        verse_id=verse_id,
        source_locator=source_locator,
    )


def convert_doc_to_docx(path: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="structure-normalizer-doc-"))
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


def cleanup_temp(temp_dir: Optional[Path]) -> None:
    if temp_dir and temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)


class StyleCatalog:
    def __init__(self, root):
        self.by_id: Dict[str, str] = {}
        self.default_by_type: Dict[str, str] = {}
        for style in root.xpath(".//w:style", namespaces=NS):
            style_id = style.get(f"{W}styleId")
            name_node = style.find("w:name", namespaces=NS)
            name = name_node.get(f"{W}val") if name_node is not None else style_id
            if style_id and name:
                self.by_id[style_id] = name
            style_type = style.get(f"{W}type") or "unknown"
            if style.get(f"{W}default") in {"1", "true", "True"} and style_type not in self.default_by_type:
                self.default_by_type[style_type] = name

    def style_name(self, style_id: Optional[str]) -> Optional[str]:
        if not style_id:
            return None
        return self.by_id.get(style_id, style_id)

    def default_style_name(self, style_type: str) -> Optional[str]:
        return self.default_by_type.get(style_type)


def visible_text(node) -> str:
    return "".join(t.text or "" for t in node.xpath(".//w:t", namespaces=NS)).strip()


def count_footnote_refs(node) -> int:
    return len(node.xpath(".//w:footnoteReference", namespaces=NS))


def extract_docx_document(path: Path) -> StructuredDocument:
    blocks: List[StructuredBlock] = []
    with zipfile.ZipFile(path, "r") as zf:
        styles_root = etree.fromstring(zf.read("word/styles.xml"))
        catalog = StyleCatalog(styles_root)
        default_style = catalog.default_style_name("paragraph")
        root = etree.fromstring(zf.read("word/document.xml"))
        for idx, paragraph in enumerate(root.xpath(".//w:body/w:p", namespaces=NS), 1):
            text = visible_text(paragraph)
            if not clean_text(text):
                continue
            p_style = paragraph.find("w:pPr/w:pStyle", namespaces=NS)
            style_name = catalog.style_name(p_style.get(f"{W}val")) if p_style is not None else default_style
            blocks.append(
                build_block(
                    index=len(blocks) + 1,
                    part="word/document.xml",
                    section="body",
                    text=text,
                    style_name=style_name,
                    footnote_refs=count_footnote_refs(paragraph),
                )
            )

    metadata = {
        "block_count": len(blocks),
        "section_counts": dict(Counter(block.section for block in blocks)),
        "kind_counts": dict(Counter(block.kind for block in blocks)),
    }
    return StructuredDocument(
        version=1,
        source_path=str(path),
        source_format="docx",
        metadata=metadata,
        blocks=blocks,
    )


def extract_text_document(path: Path, source_format: str) -> StructuredDocument:
    text = path.read_text(encoding="utf-8", errors="ignore")
    raw_blocks = [clean_text(chunk) for chunk in re.split(r"\n\s*\n+", text)]
    blocks: List[StructuredBlock] = []
    for raw in raw_blocks:
        if not raw:
            continue
        blocks.append(
            build_block(
                index=len(blocks) + 1,
                part="text",
                section="body",
                text=raw,
                style_name=None,
                footnote_refs=0,
            )
        )

    metadata = {
        "block_count": len(blocks),
        "section_counts": dict(Counter(block.section for block in blocks)),
        "kind_counts": dict(Counter(block.kind for block in blocks)),
    }
    return StructuredDocument(
        version=1,
        source_path=str(path),
        source_format=source_format,
        metadata=metadata,
        blocks=blocks,
    )


def clean_candidate_text(text: str) -> str:
    text = unescape(text or "")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    text = re.sub(r"^[\"'«„“”]+", "", text)
    text = re.sub(r"[\"'»“”.,;:!?]+$", "", text)
    return text.strip()


def looks_like_word_for_word_block(text: str) -> bool:
    text = clean_candidate_text(text)
    if not text:
        return False
    emdash_count = text.count(" — ")
    semicolon_count = text.count(";")
    if emdash_count >= 2 and semicolon_count >= 1:
        return True
    if re.search(r"\b—\s+[А-Яа-яЁё]", text) and semicolon_count >= 2:
        return True
    return False


def looks_like_transliteration_block(text: str) -> bool:
    text = clean_candidate_text(text)
    if not text:
        return False
    return looks_like_transliteration_text(text) and len(text.split()) <= 24


def looks_like_prose_paragraph(text: str) -> bool:
    text = clean_candidate_text(text)
    if not text:
        return False
    words = text.split()
    if len(words) < 8:
        return False
    if looks_like_word_for_word_block(text):
        return False
    if looks_like_transliteration_block(text):
        return False
    return bool(re.search(r"[.!?…:]", text))


class FragmentExtractor(HTMLParser):
    BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: List[str] = []
        self.italic_fragments: List[str] = []
        self._current: List[str] = []
        self._italic_current: List[str] = []
        self._italic_depth = 0

    def flush_block(self) -> None:
        text = clean_candidate_text("".join(self._current))
        if text:
            self.blocks.append(text)
        self._current = []

    def flush_italic(self) -> None:
        text = clean_candidate_text("".join(self._italic_current))
        if text:
            self.italic_fragments.append(text)
        self._italic_current = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"em", "i"}:
            self._italic_depth += 1
        elif tag == "br":
            self._current.append("\n")
            if self._italic_depth:
                self._italic_current.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"em", "i"}:
            self._italic_depth = max(0, self._italic_depth - 1)
            if self._italic_depth == 0:
                self.flush_italic()
        elif tag in self.BLOCK_TAGS:
            self.flush_block()

    def handle_data(self, data: str) -> None:
        self._current.append(data)
        if self._italic_depth:
            self._italic_current.append(data)

    def close(self) -> None:
        super().close()
        self.flush_italic()
        self.flush_block()


class VedabaseStructuredParser(HTMLParser):
    BLOCK_TAGS = {"p", "div", "li", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: List[Tuple[str, str]] = []
        self.italic_fragments: List[Tuple[str, str]] = []
        self.lang: Optional[str] = None
        self.title: str = ""
        self._in_title = False
        self._title_chunks: List[str] = []
        self._current: List[str] = []
        self._italic_current: List[str] = []
        self._italic_depth = 0
        self._section_markers: List[Optional[str]] = []
        self._skip_markers: List[bool] = []
        self._capture_depth = 0
        self._skip_depth = 0

    def _class_set(self, attrs) -> set[str]:
        for key, value in attrs:
            if key.lower() == "class":
                return {item.strip() for item in str(value).split() if item.strip()}
        return set()

    def _active_section(self) -> Optional[str]:
        for marker in reversed(self._section_markers):
            if marker:
                return marker
        return None

    def flush_block(self) -> None:
        if self._capture_depth <= 0 or self._skip_depth > 0:
            self._current = []
            return
        section = self._active_section()
        text = clean_text("".join(self._current))
        self._current = []
        if not text or text in VEDABASE_IGNORED_BLOCK_TEXTS or not section:
            return
        self.blocks.append((section, text))

    def flush_italic(self) -> None:
        section = self._active_section()
        text = clean_candidate_text("".join(self._italic_current))
        self._italic_current = []
        if text and section:
            self.italic_fragments.append((section, text))

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "html":
            for key, value in attrs:
                if key.lower() == "lang":
                    self.lang = str(value).strip()
                    break
        if tag == "title":
            self._in_title = True

        classes = self._class_set(attrs)
        section_here = None
        for class_name, section in VEDABASE_SECTION_CLASSES.items():
            if class_name in classes:
                section_here = section
                break
        self._section_markers.append(section_here)
        if section_here:
            self._capture_depth += 1

        skip_here = tag in {"h1", "h2", "h3", "h4", "h5", "h6"}
        self._skip_markers.append(skip_here)
        if skip_here:
            self._skip_depth += 1

        if self._capture_depth > 0 and self._skip_depth == 0:
            if tag in {"em", "i"}:
                self._italic_depth += 1
            elif tag == "br":
                self._current.append("\n")
                if self._italic_depth:
                    self._italic_current.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
            self.title = clean_text("".join(self._title_chunks))
            self._title_chunks = []

        if self._capture_depth > 0 and self._skip_depth == 0:
            if tag in {"em", "i"}:
                self._italic_depth = max(0, self._italic_depth - 1)
                if self._italic_depth == 0:
                    self.flush_italic()
            elif tag in self.BLOCK_TAGS:
                self.flush_block()

        if self._skip_markers:
            skip_here = self._skip_markers.pop()
            if skip_here and self._skip_depth > 0:
                self._skip_depth -= 1

        if self._section_markers:
            section_here = self._section_markers.pop()
            if section_here and self._capture_depth > 0:
                self._capture_depth -= 1

        if self._capture_depth == 0:
            self._current = []
            self._italic_current = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_chunks.append(data)
        if self._capture_depth <= 0 or self._skip_depth > 0:
            return
        self._current.append(data)
        if self._italic_depth:
            self._italic_current.append(data)

    def close(self) -> None:
        super().close()
        self.flush_italic()
        self.flush_block()


def infer_vedabase_web_path(path: Path) -> str:
    parts = list(path.parts)
    try:
        idx = parts.index("vedabase")
    except ValueError:
        return ""
    relative = parts[idx + 1 :]
    if relative and relative[-1].lower() == "index.html":
        relative = relative[:-1]
    web_path = "/" + "/".join(relative)
    return web_path.rstrip("/") + "/" if web_path != "/" else "/"


def normalize_vedabase_web_path(web_path: str) -> str:
    parts = [part for part in str(web_path or "").split("/") if part]
    if not parts:
        return ""
    normalized = "/" + "/".join(parts)
    return normalized.rstrip("/") + "/" if normalized != "/" else "/"


def parse_vedabase_path(path_or_web_path: Path | str) -> VedabasePathInfo:
    raw_value = str(path_or_web_path)
    if isinstance(path_or_web_path, Path) or raw_value.endswith(".html") or "/vedabase/" in raw_value:
        source_path = raw_value
        web_path = infer_vedabase_web_path(Path(raw_value))
    else:
        source_path = raw_value
        web_path = normalize_vedabase_web_path(raw_value)

    parts = [part for part in web_path.strip("/").split("/") if part]
    locale = parts[0] if parts else ""
    library_parts = parts[2:] if len(parts) >= 2 and parts[1] == "library" else []
    root_id = library_parts[0] if library_parts else ""
    work_id = root_id
    chapter_depth: Optional[int] = None
    if root_id == "bg":
        work_id = "bg"
        chapter_depth = 2
    elif root_id == "sb":
        work_id = "sb"
        chapter_depth = 3
    elif root_id == "cc":
        work_id = f"cc/{library_parts[1]}" if len(library_parts) >= 2 else "cc"
        chapter_depth = 3

    page_type = "other"
    chapter_parts: Optional[List[str]] = None
    verse_id: Optional[str] = None
    if len(parts) < 2 or parts[1] != "library":
        page_type = "other"
    elif not library_parts:
        page_type = "library_index"
    elif library_parts[-1] == "advanced-view":
        page_type = "advanced_view"
        if chapter_depth is not None and len(library_parts[:-1]) == chapter_depth:
            chapter_parts = library_parts[:-1]
    elif chapter_depth is None:
        page_type = "work" if len(library_parts) == 1 else "other"
    elif len(library_parts) == 1:
        page_type = "work"
    elif len(library_parts) < chapter_depth:
        page_type = "subwork"
    elif len(library_parts) == chapter_depth:
        page_type = "chapter"
        chapter_parts = library_parts
    elif len(library_parts) == chapter_depth + 1:
        page_type = "verse"
        chapter_parts = library_parts[:-1]
        verse_id = library_parts[-1]
    else:
        page_type = "other"
        chapter_parts = library_parts[:chapter_depth]

    chapter_number = chapter_parts[-1] if chapter_parts else None
    chapter_key = "/".join(chapter_parts[1:]) if chapter_parts and len(chapter_parts) > 1 else None
    chapter_web_path = ""
    advanced_view_web_path = ""
    if chapter_parts:
        chapter_web_path = normalize_vedabase_web_path("/" + "/".join(parts[:2] + chapter_parts))
        advanced_view_web_path = normalize_vedabase_web_path(chapter_web_path + "advanced-view/")

    return VedabasePathInfo(
        source_path=source_path,
        web_path=web_path,
        locale=locale,
        library_parts=library_parts,
        root_id=root_id,
        work_id=work_id,
        page_type=page_type,
        chapter_number=chapter_number,
        chapter_key=chapter_key,
        chapter_web_path=chapter_web_path or None,
        advanced_view_web_path=advanced_view_web_path or None,
        verse_id=verse_id,
        path_depth=len(library_parts),
    )


def find_vedabase_root(path: Path) -> Optional[Path]:
    anchor = path if path.is_dir() else path.parent
    for candidate in [anchor] + list(anchor.parents):
        if candidate.name == "vedabase":
            return candidate
    return None


def vedabase_html_path_from_web_path(vedabase_root: Path, web_path: str) -> Path:
    normalized = normalize_vedabase_web_path(web_path)
    if not normalized:
        die("Cannot resolve empty Vedabase web path")
    return vedabase_root / normalized.strip("/") / "index.html"


def vedabase_verse_sort_key(verse_id: Optional[str]) -> Tuple[int, int, str]:
    token = str(verse_id or "")
    numbers = [int(chunk) for chunk in re.findall(r"\d+", token)]
    first = numbers[0] if numbers else 10**9
    second = numbers[1] if len(numbers) > 1 else -1
    return (first, second, token)


def list_vedabase_verse_page_paths(chapter_dir: Path) -> List[Path]:
    paths: List[Path] = []
    if not chapter_dir.exists():
        return paths
    for child in sorted(chapter_dir.iterdir()):
        if not child.is_dir() or child.name == "advanced-view":
            continue
        candidate = child / "index.html"
        if not candidate.exists():
            continue
        info = parse_vedabase_path(candidate)
        if info.page_type == "verse":
            paths.append(candidate)
    return sorted(paths, key=lambda path: vedabase_verse_sort_key(parse_vedabase_path(path).verse_id))


def extract_vedabase_document_from_raw(
    raw: str,
    *,
    source_path: str,
    web_path: str = "",
    title: str = "",
    lang: Optional[str] = None,
) -> StructuredDocument:
    parser = VedabaseStructuredParser()
    parser.feed(raw)
    parser.close()

    normalized_web_path = normalize_vedabase_web_path(web_path)
    path_info = parse_vedabase_path(normalized_web_path) if normalized_web_path else None
    blocks: List[StructuredBlock] = []
    for section, text in parser.blocks:
        blocks.append(
            build_block(
                index=len(blocks) + 1,
                part="vedabase_html",
                section=section,
                text=text,
                style_name=f"vedabase:{section}",
                footnote_refs=0,
                verse_id=path_info.verse_id if path_info else None,
                source_locator=normalized_web_path or None,
            )
        )

    section_counts = dict(Counter(block.section for block in blocks))
    kind_counts = dict(Counter(block.kind for block in blocks))
    metadata = {
        "title": title or parser.title,
        "lang": lang or parser.lang,
        "vedabase_path": normalized_web_path,
        "block_count": len(blocks),
        "section_counts": section_counts,
        "kind_counts": kind_counts,
        "italic_fragments": [text for _section, text in parser.italic_fragments],
    }
    if path_info:
        metadata["page_info"] = path_info.to_dict()
    return StructuredDocument(
        version=1,
        source_path=source_path,
        source_format="vedabase_html",
        metadata=metadata,
        blocks=blocks,
    )


def extract_vedabase_html_document(path: Path) -> StructuredDocument:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    return extract_vedabase_document_from_raw(
        raw,
        source_path=str(path),
        web_path=infer_vedabase_web_path(path),
    )


def extract_verse_id_from_label(label: str) -> str:
    normalized = clean_text(label).rstrip(":")
    match = VERSE_HEADING_PATTERN.match(normalized)
    if match:
        return match.group(1).strip().rstrip(":")
    return normalized


def load_html_tree(path: Path):
    raw = path.read_text(encoding="utf-8", errors="ignore")
    try:
        return raw, lxml_html.fromstring(raw)
    except (etree.ParserError, ValueError) as exc:
        die(f"Could not parse HTML: {path} ({exc})")


def first_xpath_text(doc, expr: str) -> str:
    return clean_text(str(doc.xpath(f"string({expr})")))


def count_chapter_verse_links(doc, chapter_web_path: str) -> int:
    links = set()
    for raw in doc.xpath("//*[@href]/@href"):
        href = normalize_vedabase_web_path(str(raw or ""))
        if not href:
            continue
        info = parse_vedabase_path(href)
        if info.page_type == "verse" and info.chapter_web_path == chapter_web_path:
            links.add(href)
    return len(links)


def relabel_structured_blocks(
    blocks: Iterable[StructuredBlock],
    *,
    start_index: int,
    part: str,
    verse_id: str,
    source_locator: str,
) -> List[StructuredBlock]:
    rebased: List[StructuredBlock] = []
    next_index = start_index
    for block in blocks:
        rebased.append(
            StructuredBlock(
                index=next_index,
                part=part,
                section=block.section,
                text=block.text,
                style_name=block.style_name,
                kind=block.kind,
                word_count=block.word_count,
                char_count=block.char_count,
                footnote_refs=block.footnote_refs,
                digit_signature=block.digit_signature,
                has_quote_marks=block.has_quote_marks,
                translit_score=block.translit_score,
                verse_id=verse_id,
                source_locator=source_locator,
            )
        )
        next_index += 1
    return rebased


def section_map_from_blocks(blocks: Iterable[StructuredBlock]) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    for block in blocks:
        sections.setdefault(block.section, []).append(block.text)
    return sections


def resolve_vedabase_chapter_context(path: Path) -> VedabaseChapterContext:
    if not path.exists():
        die(f"Vedabase input not found: {path}")
    vedabase_root = find_vedabase_root(path)
    if vedabase_root is None:
        die(f"Could not locate Vedabase root for {path}")

    reference_path = path
    if path.is_dir():
        if path.name == "advanced-view":
            reference_path = path / "index.html"
        else:
            reference_path = path / "index.html"
    info = parse_vedabase_path(reference_path)

    chapter_web_path = ""
    if info.page_type == "chapter":
        chapter_web_path = info.web_path
    elif info.page_type in {"advanced_view", "verse"}:
        chapter_web_path = info.chapter_web_path or ""

    if not chapter_web_path:
        die(f"Input does not resolve to a Vedabase chapter: {path}")

    chapter_info = parse_vedabase_path(chapter_web_path)
    chapter_page_path = vedabase_html_path_from_web_path(vedabase_root, chapter_web_path)
    if not chapter_page_path.exists():
        chapter_page_path = None
    chapter_dir = chapter_page_path.parent if chapter_page_path else vedabase_html_path_from_web_path(vedabase_root, chapter_web_path).parent

    advanced_view_path = None
    if chapter_info.advanced_view_web_path:
        candidate = vedabase_html_path_from_web_path(vedabase_root, chapter_info.advanced_view_web_path)
        if candidate.exists():
            advanced_view_path = candidate

    return VedabaseChapterContext(
        vedabase_root=vedabase_root,
        chapter_dir=chapter_dir,
        chapter_page_path=chapter_page_path,
        advanced_view_path=advanced_view_path,
        chapter_info=chapter_info,
    )


def assemble_vedabase_chapter_from_advanced_view(context: VedabaseChapterContext) -> VedabaseChapter:
    if context.advanced_view_path is None:
        die(f"No advanced-view file for {context.chapter_info.chapter_web_path}")

    raw, doc = load_html_tree(context.advanced_view_path)
    title = first_xpath_text(doc, "//title[1]")
    chapter_title = first_xpath_text(doc, "//h1[1]") or title
    lang = first_xpath_text(doc, "/html/@lang") or context.chapter_info.locale
    containers = doc.xpath('//*[contains(concat(" ", normalize-space(@class), " "), " av-verses ")]')
    if not containers:
        die(f"No av-verses container found in {context.advanced_view_path}")

    chapter_blocks: List[StructuredBlock] = []
    verses: List[VedabaseVerse] = []
    for child in containers[0]:
        if not isinstance(child.tag, str):
            continue
        h2_nodes = child.xpath(".//h2[1]")
        if not h2_nodes:
            continue
        h2 = h2_nodes[0]
        verse_label = clean_text(" ".join(h2.itertext()))
        heading_id = h2.get("id")
        hrefs = h2.xpath(".//a/@href")
        verse_web_path = normalize_vedabase_web_path(hrefs[0]) if hrefs else ""
        verse_info = parse_vedabase_path(verse_web_path) if verse_web_path else None
        verse_id = verse_info.verse_id if verse_info and verse_info.verse_id else extract_verse_id_from_label(verse_label)
        fragment = etree.tostring(child, encoding="unicode")
        document = extract_vedabase_document_from_raw(
            fragment,
            source_path=str(context.advanced_view_path),
            web_path=verse_web_path,
            lang=lang,
        )
        rebased_blocks = relabel_structured_blocks(
            document.blocks,
            start_index=len(chapter_blocks) + 1,
            part=f"verse:{verse_id}",
            verse_id=verse_id,
            source_locator=verse_web_path or context.chapter_info.advanced_view_web_path or "",
        )
        chapter_blocks.extend(rebased_blocks)
        verses.append(
            VedabaseVerse(
                verse_index=len(verses) + 1,
                verse_id=verse_id,
                verse_label=verse_label,
                title=document.metadata.get("title") or None,
                heading_id=heading_id,
                source_path=str(context.advanced_view_path),
                vedabase_path=verse_web_path or "",
                source_mode="advanced_view",
                sections=section_map_from_blocks(rebased_blocks),
                blocks=rebased_blocks,
            )
        )

    metadata = {
        "title": title,
        "chapter_title": chapter_title,
        "lang": lang,
        "vedabase_path": context.chapter_info.chapter_web_path,
        "advanced_view_path": context.chapter_info.advanced_view_web_path,
        "work_id": context.chapter_info.work_id,
        "chapter_number": context.chapter_info.chapter_number,
        "chapter_key": context.chapter_info.chapter_key,
        "source_mode": "advanced_view",
        "verse_count": len(verses),
        "linked_verse_count": len(verses),
        "is_partial_chapter": False,
        "block_count": len(chapter_blocks),
        "section_counts": dict(Counter(block.section for block in chapter_blocks)),
        "kind_counts": dict(Counter(block.kind for block in chapter_blocks)),
    }
    return VedabaseChapter(
        version=1,
        source_path=str(context.advanced_view_path),
        source_format="vedabase_chapter",
        metadata=metadata,
        blocks=chapter_blocks,
        verses=verses,
    )


def assemble_vedabase_chapter_from_verse_pages(context: VedabaseChapterContext) -> VedabaseChapter:
    verse_paths = list_vedabase_verse_page_paths(context.chapter_dir)
    if not verse_paths:
        die(f"No verse pages found under {context.chapter_dir}")

    chapter_title = ""
    title = ""
    lang = context.chapter_info.locale
    linked_verse_count = 0
    if context.chapter_page_path and context.chapter_page_path.exists():
        _raw, doc = load_html_tree(context.chapter_page_path)
        title = first_xpath_text(doc, "//title[1]")
        chapter_title = first_xpath_text(doc, "//h1[1]") or title
        lang = first_xpath_text(doc, "/html/@lang") or lang
        linked_verse_count = count_chapter_verse_links(doc, context.chapter_info.web_path)

    chapter_blocks: List[StructuredBlock] = []
    verses: List[VedabaseVerse] = []
    for verse_path in verse_paths:
        document = extract_vedabase_html_document(verse_path)
        info = parse_vedabase_path(verse_path)
        verse_id = info.verse_id or verse_path.parent.name
        verse_web_path = document.metadata.get("vedabase_path") or info.web_path
        rebased_blocks = relabel_structured_blocks(
            document.blocks,
            start_index=len(chapter_blocks) + 1,
            part=f"verse:{verse_id}",
            verse_id=verse_id,
            source_locator=str(verse_web_path),
        )
        chapter_blocks.extend(rebased_blocks)
        verses.append(
            VedabaseVerse(
                verse_index=len(verses) + 1,
                verse_id=verse_id,
                verse_label=f"TEXT {verse_id}",
                title=document.metadata.get("title") or None,
                source_path=str(verse_path),
                vedabase_path=str(verse_web_path),
                source_mode="verse_page",
                sections=section_map_from_blocks(rebased_blocks),
                blocks=rebased_blocks,
            )
        )
        if not lang:
            lang = str(document.metadata.get("lang") or "")

    metadata = {
        "title": title,
        "chapter_title": chapter_title or title,
        "lang": lang,
        "vedabase_path": context.chapter_info.chapter_web_path,
        "advanced_view_path": context.chapter_info.advanced_view_web_path,
        "work_id": context.chapter_info.work_id,
        "chapter_number": context.chapter_info.chapter_number,
        "chapter_key": context.chapter_info.chapter_key,
        "source_mode": "verse_pages",
        "verse_count": len(verses),
        "linked_verse_count": linked_verse_count,
        "is_partial_chapter": bool(linked_verse_count and linked_verse_count != len(verses)),
        "block_count": len(chapter_blocks),
        "section_counts": dict(Counter(block.section for block in chapter_blocks)),
        "kind_counts": dict(Counter(block.kind for block in chapter_blocks)),
    }
    return VedabaseChapter(
        version=1,
        source_path=str(context.chapter_page_path or context.chapter_dir),
        source_format="vedabase_chapter",
        metadata=metadata,
        blocks=chapter_blocks,
        verses=verses,
    )


def assemble_vedabase_chapter(path: Path) -> VedabaseChapter:
    context = resolve_vedabase_chapter_context(path)
    if context.advanced_view_path and context.advanced_view_path.exists():
        return assemble_vedabase_chapter_from_advanced_view(context)
    return assemble_vedabase_chapter_from_verse_pages(context)


def extract_vedabase_text_fragments(path: Path) -> Tuple[List[str], List[str]]:
    document = extract_vedabase_html_document(path)
    prose_blocks = [
        block.text
        for block in document.blocks
        if block.section in {"translation", "purport", "commentary"} and looks_like_prose_paragraph(block.text)
    ]
    italics = [clean_candidate_text(text) for text in document.metadata.get("italic_fragments", [])]
    italics = [text for text in italics if text]
    return prose_blocks, italics


def extract_json_strings(raw: str, marker: str) -> List[str]:
    pattern = re.compile(re.escape(marker) + r'((?:[^"\\]|\\.)*)"')
    out: List[str] = []
    for match in pattern.finditer(raw):
        payload = match.group(1)
        try:
            out.append(json.loads('"' + payload + '"'))
        except json.JSONDecodeError:
            continue
    return out


def extract_generic_html_document(path: Path) -> StructuredDocument:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    fragments = extract_json_strings(raw, '__html":"')
    fragments.extend(extract_json_strings(raw, '"children":"'))
    if not fragments:
        fragments = [raw]

    blocks: List[StructuredBlock] = []
    italic_fragments: List[str] = []
    for fragment in fragments:
        parser = FragmentExtractor()
        parser.feed(fragment)
        parser.close()
        for text in parser.blocks:
            if not clean_candidate_text(text):
                continue
            blocks.append(
                build_block(
                    index=len(blocks) + 1,
                    part="html",
                    section="body",
                    text=text,
                    style_name=None,
                    footnote_refs=0,
                )
            )
        italic_fragments.extend(parser.italic_fragments)

    metadata = {
        "block_count": len(blocks),
        "section_counts": dict(Counter(block.section for block in blocks)),
        "kind_counts": dict(Counter(block.kind for block in blocks)),
        "italic_fragments": [clean_candidate_text(text) for text in italic_fragments if clean_candidate_text(text)],
    }
    return StructuredDocument(
        version=1,
        source_path=str(path),
        source_format="html",
        metadata=metadata,
        blocks=blocks,
    )


def detect_source_format(path: Path, forced_format: str = "auto") -> str:
    if forced_format != "auto":
        return forced_format
    suffix = path.suffix.lower()
    if suffix == ".doc":
        return "doc"
    if suffix == ".docx":
        return "docx"
    if suffix in {".txt", ".md"}:
        return "text"
    if suffix in {".html", ".htm"}:
        return "vedabase_html" if "/vedabase/" in str(path) else "html"
    die(f"Unsupported input format: {path.suffix}")


def normalize_source(path: Path, forced_format: str = "auto") -> Tuple[StructuredDocument, Optional[Path]]:
    if not path.exists():
        die(f"Input not found: {path}")
    source_format = detect_source_format(path, forced_format=forced_format)
    temp_dir: Optional[Path] = None
    resolved = path

    if source_format == "doc":
        resolved = convert_doc_to_docx(path)
        temp_dir = resolved.parent
        source_format = "docx"

    if source_format == "docx":
        return extract_docx_document(resolved), temp_dir
    if source_format == "text":
        return extract_text_document(resolved, source_format="text"), temp_dir
    if source_format == "vedabase_html":
        return extract_vedabase_html_document(resolved), temp_dir
    if source_format == "html":
        return extract_generic_html_document(resolved), temp_dir
    die(f"Unsupported normalization format: {source_format}")


def write_document_json(document: StructuredDocument, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
