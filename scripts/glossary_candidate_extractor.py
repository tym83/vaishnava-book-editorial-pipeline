#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""
Extract draft glossary candidates from local Vedabase HTML and BVKS/our books.

Outputs:
- glossary draft CSV
- conflicts CSV

Uses only standard library plus local CLI fallbacks:
- pdftotext for PDF
- soffice for legacy DOC fallback
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

from text_structure import extract_vedabase_text_fragments


W_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

SCRIPTURE_HINTS = (
    "бхагавад-гита",
    "шримад-бхагаватам",
    "чайтанья-чаритамрита",
    "чайтанья-бхагавата",
    "рамаяна",
    "упанишад",
    "пурана",
    "веданта",
    "веда",
    "веды",
    "гита",
)
PLACE_HINTS = (
    "вриндаван",
    "вриндавана",
    "майяпур",
    "навадвип",
    "нилачал",
    "пури",
    "радха-кунд",
    "гокула",
    "дхам",
    "дхама",
    "матх",
    "кунд",
    "гимала",
    "ямуна",
    "ганга",
)
PERSONAL_HINTS = (
    "махапрабху",
    "госвами",
    "свами",
    "прабху",
    "махарадж",
    "тхакур",
    "деви",
    "мата",
    "бабаджи",
    "ачарья",
    "ачарйа",
    "баларама",
    "вишну",
    "джаганнатх",
)
HONORIFIC_HINTS = (
    "шри",
    "шримати",
    "шрила",
    "шрипада",
)
PHILOSOPHICAL_HINTS = (
    "бхакти",
    "санньяс",
    "вайшнав",
    "карми",
    "майявади",
    "лила",
    "гуна",
    "юга",
    "экадаши",
    "шастр",
    "шакта",
    "харе кришна",
    "арати",
    "абхишека",
    "ашрам",
    "брахман",
    "брахмачари",
    "гаятри",
    "даршан",
    "исккон",
    "абхидхея",
    "бхога",
)
CANONICAL_PREFIX_SKIP_HINTS = {
    "шри",
    "шримати",
    "шрила",
    "шрипада",
    "веда",
    "веды",
    "гита",
    "дхам",
    "дхама",
    "матх",
    "кунд",
    "пури",
}
ITALIC_STYLE_HINTS = {
    "char курсив",
    "emphasis",
}
TITLE_STYLE_HINTS = {
    "heading1",
    "heading2",
    "heading3",
    "heading4",
    "заголовок 1",
    "заголовок 2",
    "заголовок 3",
    "заголовок 4",
}
DOCX_ALLOWED_PROSE_STYLE_HINTS = {
    "основной текст",
    "normal",
    "normalweb",
    "normal web",
    "normal (web)",
    "перевод шлоки",
    "цитата 1",
    "цитата 2",
    "письмо",
}
DOCX_EXCLUDED_STYLE_HINTS = {
    "заголовок",
    "heading",
    "шлока",
    "источник",
    "подпись",
    "сноска",
    "список",
    "list",
}
VEDABASE_ALLOWED_SECTION_CLASSES = {
    "av-translation",
    "av-purport",
    "av-commentary",
}
VEDABASE_SKIP_INNER_CLASSES = {
    "text-center italic",
    "av-verse_text",
    "av-synonyms",
    "av-bengali",
    "av-devanagari",
}


def remove_diacritics(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def normalize_key(text: str) -> str:
    text = clean_candidate_text(text)
    text = remove_diacritics(text).lower()
    text = text.replace("ё", "е")
    text = text.replace("—", "-").replace("–", "-")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_candidate_text(text: str) -> str:
    text = html.unescape(text or "")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    text = re.sub(r"^[\"'«„“”]+", "", text)
    text = re.sub(r"[\"'»“”.,;:!?]+$", "", text)
    if text.startswith("(") and text.endswith(")") and text.count("(") == 1 and text.count(")") == 1:
        text = text[1:-1].strip()
    text = text.strip()
    return text


def has_cyrillic(text: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", text))


def has_sanskrit_diacritics(text: str) -> bool:
    return bool(re.search(r"[\u0300-\u036fāīūṛṝḷḹṅñṭḍṇśṣṃḥĀĪŪṚṜḶḸṄÑṬḌṆŚṢṂḤ]", text))


def has_latin_letters(text: str) -> bool:
    for ch in text:
        if not ch.isalpha():
            continue
        try:
            if "LATIN" in unicodedata.name(ch):
                return True
        except ValueError:
            continue
    return False


def looks_all_caps_short(text: str) -> bool:
    compact = re.sub(r"[^A-Za-zА-Яа-яЁё]", "", text)
    return bool(compact) and compact.upper() == compact and len(compact) <= 5


def normalize_style_hint(style: str) -> str:
    style = (style or "").strip().lower()
    return re.sub(r"[\s_]+", " ", style)


def tokens_for_match(text: str) -> list[str]:
    return re.findall(r"[a-zа-яё-]+", normalize_key(text))


def contains_hint(text: str, hints: tuple[str, ...]) -> bool:
    norm = normalize_key(text)
    tokens = tokens_for_match(text)
    token_parts: list[str] = []
    for token in tokens:
        token_parts.append(token)
        token_parts.extend([part for part in token.split("-") if part])

    for hint in hints:
        hint_norm = normalize_key(hint)
        if not hint_norm:
            continue
        if " " in hint_norm:
            if re.search(rf"(?<![a-zа-яё]){re.escape(hint_norm)}(?![a-zа-яё])", norm):
                return True
            continue
        for token in token_parts:
            if token == hint_norm or token.startswith(hint_norm):
                return True
    return False


def canonical_hint_base(text: str) -> str:
    text = clean_candidate_text(text)
    if not text:
        return ""
    groups = (
        SCRIPTURE_HINTS,
        PLACE_HINTS,
        HONORIFIC_HINTS,
        PERSONAL_HINTS,
        PHILOSOPHICAL_HINTS,
    )
    token = normalize_key(text)
    if " " in token:
        return ""
    token_has_hyphen = "-" in token
    for hints in groups:
        for hint in hints:
            hint_norm = normalize_key(hint)
            if not hint_norm or " " in hint_norm:
                continue
            hint_has_hyphen = "-" in hint_norm
            if token == hint_norm:
                return hint
            if token_has_hyphen and not hint_has_hyphen:
                continue
            if hint_norm in CANONICAL_PREFIX_SKIP_HINTS:
                continue
            if len(hint_norm) >= 5 and token.startswith(hint_norm):
                return hint
            if len(hint_norm) >= 6 and hint_norm[-1] in "аеёиоуыэюя":
                stem = hint_norm[:-1]
                if len(stem) >= 4 and token.startswith(stem):
                    return hint
    return ""


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
    if has_sanskrit_diacritics(text) and len(text.split()) <= 24:
        if text.count(".") + text.count("!") + text.count("?") == 0:
            return True
    return False


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


def split_headword_variants(text: str) -> list[str]:
    text = clean_candidate_text(text)
    if not text:
        return []

    out = [text]

    m = re.match(r"^([^()]+)\(([^()]+)\)$", text)
    if m:
        base = clean_candidate_text(m.group(1))
        inside = m.group(2)
        if base:
            out.append(base)
        for part in re.split(r"[,;/]", inside):
            part = clean_candidate_text(part)
            if part:
                out.append(part)

    if "," in text and len(text) <= 80:
        for part in re.split(r"\s*,\s*", text):
            part = clean_candidate_text(part)
            if part and len(part.split()) <= 4:
                out.append(part)

    seen = set()
    deduped = []
    for item in out:
        if item and item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def categorize(text: str) -> str:
    t = normalize_key(text)
    if not t:
        return "other"
    if contains_hint(text, SCRIPTURE_HINTS):
        return "scripture_title"
    if contains_hint(text, PLACE_HINTS):
        return "place_name"
    if contains_hint(text, HONORIFIC_HINTS):
        return "honorific"
    if contains_hint(text, PERSONAL_HINTS):
        return "personal_name"
    if contains_hint(text, PHILOSOPHICAL_HINTS):
        return "philosophical_term"
    if len(t.split()) >= 2 and t[:1].isalpha():
        return "other"
    return "other"


def source_priority(label: str) -> int:
    label = label.lower()
    if "our" in label or "bvks_ru" in label:
        return 0
    if "vedabase_ru" in label:
        return 1
    if "vedabase" in label:
        return 2
    if "bvks_en" in label:
        return 3
    return 9


def diacritics_policy(variants: Iterable[str]) -> str:
    variants = list(variants)
    if not variants:
        return "draft"
    with_marks = any(has_sanskrit_diacritics(v) for v in variants)
    without_marks = any(not has_sanskrit_diacritics(v) for v in variants)
    if with_marks and without_marks:
        return "diacritics_in_quotes_only"
    if with_marks:
        return "needs_review"
    return "no_diacritics_in_prose"


def italic_policy(italic_count: int, plain_count: int) -> str:
    if italic_count and plain_count:
        return "conditional"
    if italic_count:
        return "yes"
    return "no"


def extract_json_strings(raw: str, marker: str) -> list[str]:
    pattern = re.compile(re.escape(marker) + r'((?:[^"\\]|\\.)*)"')
    out = []
    for match in pattern.finditer(raw):
        payload = match.group(1)
        try:
            out.append(json.loads('"' + payload + '"'))
        except json.JSONDecodeError:
            continue
    return out


class FragmentExtractor(HTMLParser):
    BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self.italic_fragments: list[str] = []
        self._current: list[str] = []
        self._italic_current: list[str] = []
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


class VedabaseSectionExtractor(HTMLParser):
    BLOCK_TAGS = {"p", "div", "li", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self.italic_fragments: list[str] = []
        self._current: list[str] = []
        self._italic_current: list[str] = []
        self._italic_depth = 0
        self._capture_depth = 0
        self._skip_depth = 0
        self._capture_markers: list[bool] = []
        self._skip_markers: list[bool] = []

    def _class_set(self, attrs) -> set[str]:
        for key, value in attrs:
            if key.lower() == "class":
                return {x.strip() for x in str(value).split() if x.strip()}
        return set()

    def flush_block(self) -> None:
        if self._capture_depth <= 0 or self._skip_depth > 0:
            self._current = []
            return
        text = clean_candidate_text("".join(self._current))
        if text and text not in {"Перевод", "Комментарий"} and not looks_like_word_for_word_block(text) and not looks_like_transliteration_block(text):
            self.blocks.append(text)
        self._current = []

    def flush_italic(self) -> None:
        text = clean_candidate_text("".join(self._italic_current))
        if text and not looks_like_word_for_word_block(text) and not looks_like_transliteration_block(text):
            self.italic_fragments.append(text)
        self._italic_current = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        classes = self._class_set(attrs)
        capture_here = bool(classes & VEDABASE_ALLOWED_SECTION_CLASSES)
        skip_here = bool(classes & VEDABASE_SKIP_INNER_CLASSES or tag in {"h1", "h2", "h3", "h4", "h5", "h6"})
        self._capture_markers.append(capture_here)
        self._skip_markers.append(skip_here)
        if capture_here:
            self._capture_depth += 1
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
        if self._capture_markers:
            capture_here = self._capture_markers.pop()
            if capture_here and self._capture_depth > 0:
                self._capture_depth -= 1
        if self._capture_depth == 0:
            self._current = []
            self._italic_current = []
        if self._capture_depth < 0:
            self._capture_depth = 0
        if self._skip_depth < 0:
            self._skip_depth = 0

    def handle_data(self, data: str) -> None:
        if self._capture_depth <= 0 or self._skip_depth > 0:
            return
        self._current.append(data)
        if self._italic_depth:
            self._italic_current.append(data)

    def close(self) -> None:
        super().close()
        self.flush_italic()
        self.flush_block()


def extract_html_content(path: Path) -> tuple[list[str], list[str]]:
    if "/vedabase/" in str(path):
        return extract_vedabase_text_fragments(path)

    raw = path.read_text(encoding="utf-8", errors="ignore")

    fragments = extract_json_strings(raw, '__html":"')
    fragments.extend(extract_json_strings(raw, '"children":"'))
    if not fragments:
        fragments = [raw]

    blocks: list[str] = []
    italics: list[str] = []
    for fragment in fragments:
        parser = FragmentExtractor()
        parser.feed(fragment)
        parser.close()
        blocks.extend(parser.blocks)
        italics.extend(parser.italic_fragments)
    return blocks, italics


def iter_docx_paragraphs(path: Path) -> Iterable[tuple[str, list[str], str]]:
    with zipfile.ZipFile(path) as zf:
        parts = ["word/document.xml"]
        for part in parts:
            try:
                data = zf.read(part)
            except KeyError:
                continue
            root = ET.fromstring(data)
            for p in root.findall(".//w:p", W_NS):
                para_style = ""
                p_style = p.find("./w:pPr/w:pStyle", W_NS)
                if p_style is not None:
                    para_style = p_style.attrib.get(f"{{{W_NS['w']}}}val", "")
                texts: list[str] = []
                italics: list[str] = []
                italic_buffer: list[str] = []
                italic_mode = False
                for r in p.findall("./w:r", W_NS):
                    run_text = "".join(
                        node.text or ""
                        for node in r.findall(".//w:t", W_NS)
                    )
                    if not run_text:
                        continue
                    texts.append(run_text)
                    rpr = r.find("./w:rPr", W_NS)
                    rstyle = ""
                    is_italic = False
                    if rpr is not None:
                        if rpr.find("./w:i", W_NS) is not None or rpr.find("./w:iCs", W_NS) is not None:
                            is_italic = True
                        r_style_node = rpr.find("./w:rStyle", W_NS)
                        if r_style_node is not None:
                            rstyle = r_style_node.attrib.get(f"{{{W_NS['w']}}}val", "").strip().lower()
                        if rstyle in ITALIC_STYLE_HINTS:
                            is_italic = True

                    if is_italic:
                        italic_buffer.append(run_text)
                        italic_mode = True
                    else:
                        if italic_mode:
                            italics.append(clean_candidate_text("".join(italic_buffer)))
                            italic_buffer = []
                            italic_mode = False
                if italic_buffer:
                    italics.append(clean_candidate_text("".join(italic_buffer)))
                paragraph = clean_candidate_text("".join(texts))
                if not paragraph:
                    continue
                style_hint = normalize_style_hint(para_style)
                if style_hint:
                    if any(hint in style_hint for hint in DOCX_EXCLUDED_STYLE_HINTS):
                        continue
                    if style_hint not in DOCX_ALLOWED_PROSE_STYLE_HINTS:
                        if not looks_like_prose_paragraph(paragraph):
                            continue
                elif not looks_like_prose_paragraph(paragraph):
                    continue
                if looks_like_word_for_word_block(paragraph) or looks_like_transliteration_block(paragraph):
                    continue
                yield paragraph, [x for x in italics if x], para_style


def extract_docx_content(path: Path) -> tuple[list[str], list[str]]:
    blocks: list[str] = []
    italics: list[str] = []
    for paragraph, italic_fragments, _style in iter_docx_paragraphs(path):
        blocks.append(paragraph)
        italics.extend(italic_fragments)
    return blocks, italics


def run_command(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "Command failed")
    return proc.stdout


def extract_pdf_content(path: Path) -> tuple[list[str], list[str]]:
    text = run_command(["pdftotext", "-layout", str(path), "-"])
    blocks = []
    for raw in re.split(r"\n\s*\n+", text):
        block = clean_candidate_text(raw)
        if not block:
            continue
        if not looks_like_prose_paragraph(block):
            continue
        if looks_like_word_for_word_block(block) or looks_like_transliteration_block(block):
            continue
        blocks.append(block)
    return blocks, []


def extract_doc_content(path: Path) -> tuple[list[str], list[str]]:
    with tempfile.TemporaryDirectory(prefix="glossary_doc_") as tmpdir:
        cmd = [
            "soffice",
            "--headless",
            "--convert-to",
            "txt:Text",
            "--outdir",
            tmpdir,
            str(path),
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        txt_path = Path(tmpdir) / (path.stem + ".txt")
        if not txt_path.exists():
            stderr = (proc.stderr or "").strip()
            stdout = (proc.stdout or "").strip()
            details = stderr or stdout or f"LibreOffice did not produce txt for {path}"
            raise RuntimeError(details)
        text = txt_path.read_text(encoding="utf-8", errors="ignore")
    blocks = []
    for raw in re.split(r"\n\s*\n+", text):
        block = clean_candidate_text(raw)
        if not block:
            continue
        if not looks_like_prose_paragraph(block):
            continue
        if looks_like_word_for_word_block(block) or looks_like_transliteration_block(block):
            continue
        blocks.append(block)
    return blocks, []


def extract_txt_content(path: Path) -> tuple[list[str], list[str]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    blocks = []
    for raw in re.split(r"\n\s*\n+", text):
        block = clean_candidate_text(raw)
        if not block:
            continue
        if not looks_like_prose_paragraph(block):
            continue
        if looks_like_word_for_word_block(block) or looks_like_transliteration_block(block):
            continue
        blocks.append(block)
    return blocks, []


def extract_file_content(path: Path) -> tuple[list[str], list[str]]:
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return extract_html_content(path)
    if suffix == ".docx":
        return extract_docx_content(path)
    if suffix == ".pdf":
        return extract_pdf_content(path)
    if suffix == ".doc":
        return extract_doc_content(path)
    if suffix in {".txt", ".md"}:
        return extract_txt_content(path)
    raise ValueError(f"Unsupported file type: {path.suffix}")


def glossary_headwords_from_block(block: str) -> list[str]:
    if len(block) > 240:
        return []
    match = re.match(r"^([A-ZА-ЯЁ«][^—–-]{1,120}?)\s+[—–-]\s+.+$", block)
    if not match:
        return []
    head = clean_candidate_text(match.group(1))
    words = head.split()
    if not words or len(words) > 4:
        return []
    if words[0].lower() in {"а", "и", "но", "или", "да", "то", "что", "как", "если", "когда"}:
        return []
    if len(words) > 1 and words[0][:1].islower() and "-" not in head and "(" not in head:
        return []
    return split_headword_variants(head)


def looks_candidate(text: str, kind: str) -> bool:
    text = clean_candidate_text(text)
    if not text:
        return False
    if len(text) < 2 or len(text) > 120:
        return False
    if text.count(" ") > 8:
        return False
    if looks_all_caps_short(text):
        return False
    if re.search(r"https?://|www\.|@|\.com\b", text, re.I):
        return False
    if "<" in text or ">" in text:
        return False
    if "(" in text or ")" in text:
        return False
    if has_latin_letters(text):
        return False
    if re.search(r"\d", text):
        return False
    if re.match(r"^[,;:.\-–—]", text):
        return False
    if not re.match(r"^[А-Яа-яЁё]", text):
        return False
    if not has_cyrillic(text):
        return False
    if has_sanskrit_diacritics(text):
        return False

    if kind == "glossary_headword":
        return categorize(text) != "other"

    if kind == "italic":
        words = text.split()
        if len(words) > 3:
            return False
        lowered = remove_diacritics(text).lower()
        if "," in text or ";" in text or ":" in text:
            return False
        if text.startswith("-") or text.endswith("-"):
            return False
        if re.search(r"[/.…]", text):
            return False
        if kind == "italic" and categorize(text) == "other":
            return False
        return True

    lowered = normalize_key(text)
    if contains_hint(text, SCRIPTURE_HINTS + PLACE_HINTS + PERSONAL_HINTS + HONORIFIC_HINTS + PHILOSOPHICAL_HINTS):
        return True
    return has_sanskrit_diacritics(text)


def source_examples_join(examples: list[str]) -> str:
    return " | ".join(examples[:5])


def source_file_fragment(source_file: str) -> str:
    parts = Path(source_file).parts
    if len(parts) >= 4:
        return "/".join(parts[-4:])
    return Path(source_file).name


@dataclass
class CandidateAggregate:
    key: str
    variants: Counter[str] = field(default_factory=Counter)
    source_counts: Counter[str] = field(default_factory=Counter)
    category_counts: Counter[str] = field(default_factory=Counter)
    kind_counts: Counter[str] = field(default_factory=Counter)
    italic_count: int = 0
    plain_count: int = 0
    examples: list[str] = field(default_factory=list)
    files: set[str] = field(default_factory=set)

    def add(self, text: str, source_label: str, source_file: str, context: str, italic: bool, kind: str) -> None:
        self.variants[text] += 1
        self.source_counts[source_label] += 1
        self.category_counts[categorize(text)] += 1
        self.kind_counts[kind] += 1
        if italic:
            self.italic_count += 1
        else:
            self.plain_count += 1
        self.files.add(source_file)
        example = f"{source_label}:{source_file_fragment(source_file)}:{context[:120]}"
        if len(self.examples) < 5 and example not in self.examples:
            self.examples.append(example)

    def choose_approved_form(self) -> tuple[str, str]:
        preferred_variants = [
            variant
            for variant in self.variants
            if normalize_key(variant) == self.key or normalize_key(canonical_hint_base(variant)) == self.key
        ]
        if preferred_variants:
            preferred_variants = sorted(
                preferred_variants,
                key=lambda v: (
                    normalize_key(v) != self.key,
                    has_sanskrit_diacritics(v),
                    len(v),
                    v[:1].isupper(),
                    -self.variants[v],
                ),
            )
            approved = preferred_variants[0]
        else:
            ordered = sorted(
                self.variants.items(),
                key=lambda kv: (
                    has_sanskrit_diacritics(kv[0]),
                    -kv[1],
                    len(kv[0]),
                ),
            )
            approved = ordered[0][0] if ordered else self.key
        preferred_source = min(self.source_counts, key=source_priority) if self.source_counts else ""
        return approved, preferred_source

    def has_primary_support(self) -> bool:
        for label in self.source_counts:
            lowered = label.lower()
            if "our" in lowered or "bvks_ru" in lowered:
                return True
        return False


def iter_supported_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".html", ".htm", ".docx", ".doc", ".pdf", ".txt", ".md"}:
            continue
        yield path


def extract_candidates_from_file(path: Path, source_label: str, aggregates: dict[str, CandidateAggregate], errors: list[str]) -> None:
    try:
        blocks, italic_fragments = extract_file_content(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{path}: {exc}")
        return

    for block in blocks:
        context = clean_candidate_text(block)
        for headword in glossary_headwords_from_block(block):
            if not looks_candidate(headword, "glossary_headword"):
                continue
            key = normalize_key(canonical_hint_base(headword) or headword)
            if not key:
                continue
            aggregates.setdefault(key, CandidateAggregate(key=key)).add(
                text=headword,
                source_label=source_label,
                source_file=str(path),
                context=context,
                italic=False,
                kind="glossary_headword",
            )

    for frag in italic_fragments:
        frag = clean_candidate_text(frag)
        if not looks_candidate(frag, "italic"):
            continue
        key = normalize_key(canonical_hint_base(frag) or frag)
        if not key:
            continue
        aggregates.setdefault(key, CandidateAggregate(key=key)).add(
            text=frag,
            source_label=source_label,
            source_file=str(path),
            context=frag,
            italic=True,
            kind="italic",
        )


def iter_base_rows(
    aggregates: dict[str, CandidateAggregate],
    high_signal_only: bool = False,
    include_vedabase_only: bool = False,
):
    for idx, key in enumerate(sorted(aggregates), start=1):
        agg = aggregates[key]
        if not include_vedabase_only and not agg.has_primary_support():
            continue
        approved, preferred_source = agg.choose_approved_form()
        category = agg.category_counts.most_common(1)[0][0] if agg.category_counts else "other"
        status = "draft"
        if len(agg.variants) > 1 or italic_policy(agg.italic_count, agg.plain_count) == "conditional":
            status = "needs_review"
        if high_signal_only:
            if agg.kind_counts.get("glossary_headword", 0) == 0 and category == "other":
                continue
        yield {
            "id": f"term-{idx:05d}",
            "lemma_ru": approved,
            "lemma_en": "",
            "category": category,
            "approved_form": approved,
            "declension_notes": "",
            "italic_required": italic_policy(agg.italic_count, agg.plain_count),
            "diacritics_policy": diacritics_policy(agg.variants),
            "capitalization_notes": "",
            "variants_found": " | ".join(f"{v} [{c}]" for v, c in agg.variants.most_common()),
            "preferred_source": preferred_source,
            "source_examples": source_examples_join(agg.examples),
            "editor_decision": "",
            "status": status,
            "notes": "auto-generated draft",
        }


def write_base_csv(
    path: Path,
    aggregates: dict[str, CandidateAggregate],
    high_signal_only: bool = False,
    include_vedabase_only: bool = False,
) -> None:
    fieldnames = [
        "id",
        "lemma_ru",
        "lemma_en",
        "category",
        "approved_form",
        "declension_notes",
        "italic_required",
        "diacritics_policy",
        "capitalization_notes",
        "variants_found",
        "preferred_source",
        "source_examples",
        "editor_decision",
        "status",
        "notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in iter_base_rows(
            aggregates,
            high_signal_only=high_signal_only,
            include_vedabase_only=include_vedabase_only,
        ):
            writer.writerow(row)


def write_conflicts_csv(path: Path, aggregates: dict[str, CandidateAggregate], include_vedabase_only: bool = False) -> None:
    fieldnames = [
        "normalized_key",
        "approved_form",
        "variant_count",
        "variants",
        "italic_required",
        "diacritics_policy",
        "sources",
        "examples",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for key in sorted(aggregates):
            agg = aggregates[key]
            if not include_vedabase_only and not agg.has_primary_support():
                continue
            italic_req = italic_policy(agg.italic_count, agg.plain_count)
            dia_policy = diacritics_policy(agg.variants)
            if len(agg.variants) <= 1 and italic_req != "conditional" and dia_policy != "diacritics_in_quotes_only":
                continue
            approved, _preferred_source = agg.choose_approved_form()
            writer.writerow(
                {
                    "normalized_key": key,
                    "approved_form": approved,
                    "variant_count": len(agg.variants),
                    "variants": " | ".join(f"{v} [{c}]" for v, c in agg.variants.most_common()),
                    "italic_required": italic_req,
                    "diacritics_policy": dia_policy,
                    "sources": " | ".join(f"{s} [{c}]" for s, c in agg.source_counts.most_common()),
                    "examples": source_examples_join(agg.examples),
                }
            )


def write_summary(path: Path, aggregates: dict[str, CandidateAggregate], errors: list[str], sources: list[tuple[str, str]]) -> None:
    kept = [agg for agg in aggregates.values() if agg.has_primary_support()]
    lines = []
    lines.append("# Glossary Extraction Summary")
    lines.append("")
    lines.append("## Sources")
    for label, root in sources:
        lines.append(f"- `{label}`: `{root}`")
    lines.append("")
    lines.append(f"- raw normalized entries: {len(aggregates)}")
    lines.append(f"- entries written to glossary: {len(kept)}")
    lines.append(f"- vedabase-only entries dropped: {len(aggregates) - len(kept)}")
    lines.append(f"- entries with conflicts/review: {sum(1 for agg in kept if len(agg.variants) > 1 or italic_policy(agg.italic_count, agg.plain_count) == 'conditional' or diacritics_policy(agg.variants) == 'diacritics_in_quotes_only')}")
    lines.append("")
    lines.append("## Top categories")
    cat_counter = Counter()
    for agg in kept:
        if agg.category_counts:
            cat_counter[agg.category_counts.most_common(1)[0][0]] += 1
    for category, count in cat_counter.most_common():
        lines.append(f"- `{category}`: {count}")
    lines.append("")
    lines.append("## Extraction errors")
    if not errors:
        lines.append("- none")
    else:
        for err in errors[:100]:
            lines.append(f"- {err}")
        if len(errors) > 100:
            lines.append(f"- ... {len(errors) - 100} more omitted")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_sources(args) -> list[tuple[str, Path]]:
    pairs: list[tuple[str, Path]] = []
    for item in args.source:
        if "=" not in item:
            raise SystemExit(f"Source must be LABEL=PATH, got: {item}")
        label, raw_path = item.split("=", 1)
        root = Path(raw_path).expanduser()
        if not root.exists():
            raise SystemExit(f"Source path does not exist: {root}")
        pairs.append((label.strip(), root))
    return pairs


def cmd_extract(args) -> int:
    sources = parse_sources(args)
    outdir = Path(args.output_dir).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)

    aggregates: dict[str, CandidateAggregate] = {}
    errors: list[str] = []
    scanned = 0

    for label, root in sources:
        for path in iter_supported_files(root):
            scanned += 1
            extract_candidates_from_file(path, label, aggregates, errors)

    base_csv = outdir / "glossary_base_draft.csv"
    seed_csv = outdir / "glossary_seed_high_signal.csv"
    conflict_csv = outdir / "glossary_conflicts.csv"
    summary_md = outdir / "glossary_extraction_summary.md"

    write_base_csv(base_csv, aggregates)
    write_base_csv(seed_csv, aggregates, high_signal_only=True)
    write_conflicts_csv(conflict_csv, aggregates)
    write_summary(summary_md, aggregates, errors, [(label, str(root)) for label, root in sources])

    print(f"Scanned files: {scanned}")
    print(f"Entries: {len(aggregates)}")
    print(f"Draft base: {base_csv}")
    print(f"High-signal seed: {seed_csv}")
    print(f"Conflicts: {conflict_csv}")
    print(f"Summary: {summary_md}")
    if errors:
        print(f"Errors: {len(errors)}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract draft glossary candidates from local Vedabase/BVKS corpus")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_extract = sub.add_parser("extract", help="Extract draft glossary base and conflict report")
    p_extract.add_argument(
        "--source",
        action="append",
        required=True,
        help="Source in LABEL=PATH format. Can be passed multiple times.",
    )
    p_extract.add_argument(
        "--output-dir",
        required=True,
        help="Output directory for glossary CSV/MD files.",
    )
    p_extract.set_defaults(func=cmd_extract)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
