#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""
Heuristic semantic paragraph style classifier for normalized DOCX files.

v1 scope:
- classify high-confidence semantic paragraph styles:
  * Подпись к иллюстрации
  * Источник
  * Письмо
  * Шлока
  * Перевод шлоки
  * Цитата 1
- only rewrites body-like paragraphs (`Основной текст` / `Normal`) by default
- emits Markdown/JSON report with applied changes and review candidates

Examples:
  python3 docx_semantic_style_classifier.py classify in.docx out.docx
  python3 docx_semantic_style_classifier.py classify in.docx out.docx --report-md report.md --report-json report.json
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
from typing import Dict, List, Optional, Sequence, Tuple

from lxml import etree

from sanskrit_diacritics import has_sanskrit_diacritics, looks_like_sanskrit_quote


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

DEFAULT_TOC_MARKERS = ["Содержание", "Contents", "Оглавление"]
BODYLIKE_STYLES = {"Основной текст", "Normal", "Normal (Web)"}
COMBINING_MARKS = "\u0304\u0323\u0307\u0303\u0301"
VISUAL_BLOCK_LEFT_TWIPS = 1000
SCRIPTURE_PATTERN = re.compile(
    r"(?i)\b("
    r"шб|бг|чч|нп|SB|Bg|Cc|"
    r"ади-лила|мадхья-лила|антья-лила|"
    r"шри мад-бхагаватам|шримад-бхагаватам|бхагавад-гита|"
    r"шри чайтанья-чаритамрита|шри чайтанья чаритамрита"
    r")\b.*\d"
)
QUOTED_SOURCE_REF_PATTERN = re.compile(r"^\s*«[^»]{2,80}»\s+\d")
CAPTION_PATTERN = re.compile(
    r"(?i)^(изображени[ея]|подпись\b|подпись к изображени|подпись к изображениям|без подписи)\b"
)
SHORT_CAPTION_PATTERN = re.compile(
    r"(?i)^("
    r"ом̇\s+виш|"
    r"первая страница|последняя страница|место явления|бхаджан-кутир|пушпа-самадхи|"
    r"перед\s+|на\s+|во время\s+|при[её]м\s+|прибытие\s+|закладка\s+|санкиртана\s+"
    r")"
)
LETTER_PATTERN = re.compile(
    r"(?i)^(дорог[а-я]+|уважаем[а-я]+|пожалуйста,\s*примите мои смиренные поклоны|ваш слуга\b|искренне ваш\b)"
)
ABBREV_REF_PATTERN = re.compile(r"^[А-ЯЁA-Z][А-ЯЁA-Zа-яёa-z]{0,7}:\s")
VERSE_LABEL_PATTERN = re.compile(r"(?i)^текст\s+\d+[а-яa-z]?$")
CYRILLIC_TRANSLIT_MARKERS = {
    "адхокш",
    "ананта",
    "аравинд",
    "асми",
    "атма",
    "бгаван",
    "бхагав",
    "бхадж",
    "бхакт",
    "бхри",
    "бху",
    "бхув",
    "брахм",
    "вайшнав",
    "ванд",
    "вишну",
    "врадж",
    "вринд",
    "гатен",
    "гаура",
    "говинд",
    "госвам",
    "гуру",
    "джай",
    "джана",
    "джива",
    "дев",
    "дой",
    "дуратй",
    "йа",
    "йад",
    "йас",
    "йо",
    "йукта",
    "кали",
    "кама",
    "каруна",
    "криш",
    "кршн",
    "локан",
    "мад",
    "майа",
    "мам",
    "ман",
    "матах",
    "море",
    "нама",
    "нирвиш",
    "нитй",
    "ом",
    "пада",
    "прабху",
    "прабхупад",
    "прачар",
    "прем",
    "са",
    "сарасват",
    "сарва",
    "сев",
    "сукх",
    "татх",
    "томар",
    "твад",
    "ха",
    "хари",
    "чайтан",
    "чарана",
    "шакти",
    "шри",
    "шримат",
    "шунй",
}


@dataclass
class ParagraphInfo:
    index: int
    text: str
    style_name: Optional[str]
    node: etree._Element
    left_indent: int = 0
    first_line_indent: int = 0
    paragraph_italic: bool = False
    italic_run_ratio: float = 0.0
    has_break: bool = False

    @property
    def visual_indent(self) -> int:
        return max(self.left_indent, self.left_indent + max(0, self.first_line_indent))

    @property
    def is_visual_block(self) -> bool:
        return self.visual_indent >= VISUAL_BLOCK_LEFT_TWIPS


@dataclass
class Decision:
    index: int
    text: str
    old_style: Optional[str]
    new_style: Optional[str]
    confidence: str
    reason: str
    applied: bool


@dataclass
class HintRule:
    match_type: str
    value: object
    action: str
    style: Optional[str]
    note: str = ""


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


def stable_norm(text: str) -> str:
    return normalize_text(clean_text(text))


def convert_doc_to_docx(path: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="docx-semantic-style-"))
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
        die("docx_semantic_style_classifier currently supports .docx and .doc")
    return path, None


def cleanup_temp(temp_dir: Optional[Path]) -> None:
    if temp_dir and temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)


class StyleCatalog:
    def __init__(self, root):
        self.root = root
        self.by_id: Dict[str, etree._Element] = {}
        self.by_name: Dict[str, etree._Element] = {}
        self.default_by_type: Dict[str, etree._Element] = {}
        self._rebuild()

    def _rebuild(self) -> None:
        self.by_id.clear()
        self.by_name.clear()
        self.default_by_type.clear()
        for style in self.root.xpath(".//w:style", namespaces=NS):
            style_id = style.get(f"{W}styleId")
            style_type = style.get(f"{W}type") or "unknown"
            name_node = style.find("w:name", namespaces=NS)
            name = name_node.get(f"{W}val") if name_node is not None else style_id
            if style_id:
                self.by_id[style_id] = style
            if name:
                self.by_name[name] = style
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

    def ensure_style(self, target_name: str, style_type: str, base_name: Optional[str] = None) -> str:
        existing = self.by_name.get(target_name)
        if existing is not None:
            return existing.get(f"{W}styleId")

        base = self.by_name.get(base_name) if base_name else None
        if base is None:
            base = self.default_by_type.get(style_type)
        if base is None:
            die(f"No base style available to create {target_name}")

        style = copy.deepcopy(base)
        style_id = self._unique_style_id(style_type, target_name)
        style.set(f"{W}styleId", style_id)
        style.set(f"{W}type", style_type)
        style.attrib.pop(f"{W}default", None)
        style.set(f"{W}customStyle", "1")
        node = style.find("w:name", namespaces=NS)
        if node is None:
            node = etree.Element(f"{W}name")
            style.insert(0, node)
        node.set(f"{W}val", target_name)
        self.root.append(style)
        self._rebuild()
        return style_id

    def _unique_style_id(self, style_type: str, base: str) -> str:
        prefix = "P" if style_type == "paragraph" else "C"
        stem = "".join(ch for ch in base if ch.isalnum())[:16] or "Style"
        candidate = f"{prefix}_{stem}"
        idx = 1
        while candidate in self.by_id:
            idx += 1
            candidate = f"{prefix}_{stem}_{idx}"
        return candidate


def load_styles_root(z: zipfile.ZipFile):
    try:
        return etree.fromstring(z.read("word/styles.xml"))
    except KeyError:
        die("word/styles.xml not found in docx")


def ensure_canonical_styles(catalog: StyleCatalog) -> Dict[str, str]:
    style_ids: Dict[str, str] = {}
    base_map = {
        "Заголовок 1": "heading 1",
        "Заголовок 2": "heading 2",
        "Заголовок 3": "heading 3",
        "Заголовок 4": "heading 4",
        "Сноска": "footnote text",
    }
    for name in CANONICAL_PARAGRAPH_STYLES:
        style_ids[name] = catalog.ensure_style(name, "paragraph", base_name=base_map.get(name))
    return style_ids


def visible_text(p) -> str:
    chunks = []
    for node in p.xpath(".//w:t | .//w:tab | .//w:br | .//w:cr", namespaces=NS):
        if node.tag == f"{W}t":
            chunks.append(node.text or "")
        elif node.tag == f"{W}tab":
            chunks.append("\t")
        else:
            chunks.append("\n")
    return "".join(chunks).strip()


def int_attr(node, name: str) -> int:
    if node is None:
        return 0
    raw = node.get(f"{W}{name}")
    if raw is None:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def paragraph_indents(p) -> tuple[int, int]:
    ind = p.find("w:pPr/w:ind", namespaces=NS)
    return int_attr(ind, "left"), int_attr(ind, "firstLine")


def onoff_is_true(node) -> bool:
    if node is None:
        return False
    val = node.get(f"{W}val")
    if val is None:
        return True
    return val not in {"0", "false", "False", "off"}


def paragraph_has_italic(p) -> bool:
    return any(
        onoff_is_true(p.find(f"w:pPr/w:rPr/w:{tag}", namespaces=NS))
        for tag in ("i", "iCs")
    )


def italic_ratio(p) -> float:
    runs = p.xpath("./descendant::w:r", namespaces=NS)
    if not runs:
        return 0.0
    italic_runs = 0
    for run in runs:
        if any(onoff_is_true(run.find(f"w:rPr/w:{tag}", namespaces=NS)) for tag in ("i", "iCs")):
            italic_runs += 1
    return italic_runs / len(runs)


def iter_paragraphs(root) -> List[ParagraphInfo]:
    paragraphs = []
    for idx, p in enumerate(root.xpath(".//w:body//w:p", namespaces=NS), 1):
        left_indent, first_line_indent = paragraph_indents(p)
        paragraphs.append(
            ParagraphInfo(
                index=idx,
                text=visible_text(p),
                style_name=None,
                node=p,
                left_indent=left_indent,
                first_line_indent=first_line_indent,
                paragraph_italic=paragraph_has_italic(p),
                italic_run_ratio=italic_ratio(p),
                has_break=p.find(".//w:br", namespaces=NS) is not None or p.find(".//w:cr", namespaces=NS) is not None,
            )
        )
    return paragraphs


def get_paragraph_style_name(p, catalog: StyleCatalog, default_name: Optional[str]) -> Optional[str]:
    p_style = p.find("w:pPr/w:pStyle", namespaces=NS)
    if p_style is None:
        return default_name
    return catalog.style_name(p_style.get(f"{W}val"))


def set_paragraph_style(p, style_id: str) -> None:
    ppr = p.find("w:pPr", namespaces=NS)
    if ppr is None:
        ppr = etree.Element(f"{W}pPr")
        p.insert(0, ppr)
    pstyle = ppr.find("w:pStyle", namespaces=NS)
    if pstyle is None:
        pstyle = etree.Element(f"{W}pStyle")
        ppr.insert(0, pstyle)
    pstyle.set(f"{W}val", style_id)


def transliteration_score(text: str) -> int:
    score = 0
    score += sum(text.count(ch) for ch in COMBINING_MARKS)
    score += len(re.findall(r"[а-яё][̣̄̇̃́]", text, flags=re.IGNORECASE))
    score += len(re.findall(r"\b[а-яё-]{2,}[̣̄̇̃́][а-яё-]*\b", text, flags=re.IGNORECASE))
    return score


def transliteration_word_ratio(text: str) -> float:
    words = re.findall(r"[а-яёa-zA-Z0-9̣̄̇̃́-]+", clean_text(text), flags=re.IGNORECASE)
    if not words:
        return 0.0
    marked = 0
    for word in words:
        if any(mark in word for mark in COMBINING_MARKS):
            marked += 1
    return marked / len(words)


def looks_like_source(text: str) -> bool:
    t = clean_text(text)
    if not t:
        return False
    if VERSE_LABEL_PATTERN.match(t):
        return True
    if QUOTED_SOURCE_REF_PATTERN.search(t) and len(t.split()) <= 28:
        return True
    if not SCRIPTURE_PATTERN.search(t):
        return False
    word_count = len(t.split())
    if word_count <= 18:
        return True
    if t.startswith(("ШБ", "БГ", "ЧЧ", "Ади-лила", "Мадхья-лила", "Антья-лила")) and word_count <= 28:
        return True
    if t.startswith("«") and any(marker in t for marker in ("Ади-лила", "Мадхья-лила", "Антья-лила")) and word_count <= 24:
        return True
    return False


def looks_like_caption(text: str) -> bool:
    t = clean_text(text)
    if CAPTION_PATTERN.search(t):
        return True
    word_count = len(t.split())
    if word_count > 24:
        return False
    if "?" in t or "!" in t or t.endswith(":"):
        return False
    if re.search(r"\((стр\.|p\.|pp\.)\s*\d", t, flags=re.IGNORECASE):
        return True
    # Short captions often contain names with diacritics; those must not be
    # promoted to `Шлока` merely because of transliteration marks.
    if SHORT_CAPTION_PATTERN.search(t) and (has_sanskrit_diacritics(t) or word_count <= 10):
        return True
    return False


def looks_like_letter(text: str) -> bool:
    return bool(LETTER_PATTERN.search(clean_text(text)))


def looks_like_shloka(text: str) -> bool:
    t = clean_text(text)
    if not t:
        return False
    if looks_like_source(t) or looks_like_caption(t):
        return False
    if ABBREV_REF_PATTERN.match(t):
        return False
    if looks_like_sanskrit_quote(text):
        return True
    score = transliteration_score(t)
    ratio = transliteration_word_ratio(t)
    if score >= 4 and ratio >= 0.45:
        return True
    if score >= 2 and ratio >= 0.7:
        return True
    if "\n" in text and score >= 2 and ratio >= 0.35:
        return True
    if looks_like_cyrillic_transliteration_shloka(t):
        return True
    return False


def looks_like_cyrillic_transliteration_shloka(text: str) -> bool:
    original = clean_text(text)
    if re.search(r"[А-ЯЁA-Z]", original):
        return False
    t = original.casefold()
    if not t or re.search(r"[.!?«»“”\"():;,]", t):
        return False
    words = re.findall(r"[а-яё']+(?:-[а-яё']+)*", t)
    if not words or len(words) > 16:
        return False
    if len(words) == 1 and len(words[0]) < 5:
        return False
    cyrillic_words = [word for word in words if re.search(r"[а-яё]", word)]
    if len(cyrillic_words) != len(words):
        return False
    marker_hits = 0
    hyphenated = 0
    for word in words:
        if "-" in word:
            hyphenated += 1
        if any(marker in word for marker in CYRILLIC_TRANSLIT_MARKERS):
            marker_hits += 1
    if marker_hits >= 2:
        return True
    if marker_hits >= 1 and hyphenated >= 1:
        return True
    if len(words) <= 4 and marker_hits >= 1 and not any(word in {"и", "в", "на", "не", "но", "что", "как"} for word in words):
        return True
    return False


def looks_like_visual_shloka(para: ParagraphInfo) -> bool:
    text = para.text
    if looks_like_source(text) or looks_like_caption(text):
        return False
    if looks_like_shloka(text):
        return True
    if para.is_visual_block and has_sanskrit_diacritics(text) and len(clean_text(text).split()) <= 18:
        return True
    return False


def looks_like_translation_of_shloka(text: str) -> bool:
    t = clean_text(text)
    if not t:
        return False
    if t.startswith("«") and t.endswith("»"):
        return True
    if t.startswith("—"):
        return True
    return False


def looks_like_visual_quote(para: ParagraphInfo) -> bool:
    t = clean_text(para.text)
    if not t:
        return False
    if looks_like_source(t) or ABBREV_REF_PATTERN.match(t):
        return False
    if looks_like_quote(t):
        return True
    if para.is_visual_block and t.startswith(("«", "“", '"')):
        return True
    if para.is_visual_block and 8 <= len(t.split()) <= 260:
        return True
    return False


def looks_like_quote(text: str) -> bool:
    t = clean_text(text)
    if not t:
        return False
    if ABBREV_REF_PATTERN.match(t):
        return False
    if t.startswith("«") and t.endswith("»"):
        return True
    if t.startswith("«") and len(t) <= 800:
        return True
    return False


def load_hints(path: Optional[Path]) -> List[HintRule]:
    if path is None:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_rules = data.get("rules", data if isinstance(data, list) else [])
    rules: List[HintRule] = []
    for item in raw_rules:
        match = item.get("match", {})
        match_type = match.get("type")
        value = match.get("value")
        action = item.get("action", "set_style")
        style = item.get("style")
        note = item.get("note", "")
        if not match_type or value is None:
            continue
        rules.append(HintRule(match_type=match_type, value=value, action=action, style=style, note=note))
    return rules


def hint_for_paragraph(para: ParagraphInfo, rules: Sequence[HintRule]) -> Optional[HintRule]:
    norm_text = stable_norm(para.text)
    for rule in rules:
        if rule.match_type == "index" and para.index == rule.value:
            return rule
        if rule.match_type == "text" and norm_text == stable_norm(str(rule.value)):
            return rule
        if rule.match_type == "regex" and re.search(str(rule.value), para.text):
            return rule
    return None


def classify_paragraphs(
    paragraphs: List[ParagraphInfo],
    hint_rules: Optional[Sequence[HintRule]] = None,
) -> Tuple[List[Decision], List[Decision]]:
    applied: List[Decision] = []
    review: List[Decision] = []
    assigned_styles: Dict[int, str] = {}
    hint_rules = hint_rules or []

    for i, para in enumerate(paragraphs):
        text = para.text
        style = para.style_name
        if style not in BODYLIKE_STYLES:
            continue
        if not clean_text(text):
            continue

        hint = hint_for_paragraph(para, hint_rules)
        if hint is not None:
            if hint.action == "ignore":
                continue
            if hint.action == "review_only":
                review.append(
                    Decision(
                        index=para.index,
                        text=clean_text(text),
                        old_style=style,
                        new_style=hint.style,
                        confidence="hint",
                        reason=f"hint:{hint.note or hint.match_type}",
                        applied=False,
                    )
                )
                continue
            if hint.action == "set_style" and hint.style:
                applied.append(
                    Decision(
                        index=para.index,
                        text=clean_text(text),
                        old_style=style,
                        new_style=hint.style,
                        confidence="hint",
                        reason=f"hint:{hint.note or hint.match_type}",
                        applied=True,
                    )
                )
                assigned_styles[i + 1] = hint.style
                continue

        new_style = None
        confidence = None
        reason = None
        prev_assigned = assigned_styles.get(i)
        prev_prev_assigned = assigned_styles.get(i - 1)

        if looks_like_caption(text):
            new_style = "Подпись к иллюстрации"
            confidence = "high"
            reason = "caption-pattern"
        elif looks_like_source(text):
            new_style = "Источник"
            confidence = "high"
            reason = "scripture-reference-pattern"
        elif looks_like_letter(text):
            new_style = "Письмо"
            confidence = "medium"
            reason = "letter-pattern"
        elif prev_assigned in {"Шлока", "Шлока в цитате"} and looks_like_translation_of_shloka(text):
            new_style = "Перевод шлоки"
            confidence = "high"
            reason = "after-shloka-quoted-russian"
        elif looks_like_visual_shloka(para):
            new_style = "Шлока в цитате" if prev_assigned == "Цитата 1" else "Шлока"
            confidence = "high"
            reason = "visual-or-transliteration-shloka"
        elif looks_like_visual_quote(para) and (para.is_visual_block or 8 <= len(clean_text(text).split()) <= 180):
            new_style = "Цитата 1"
            confidence = "medium"
            reason = "standalone-or-visual-quote"
        else:
            next_text = paragraphs[i + 1].text if i + 1 < len(paragraphs) else ""
            next_next_text = paragraphs[i + 2].text if i + 2 < len(paragraphs) else ""

            if prev_assigned in {"Шлока", "Шлока в цитате"} and looks_like_translation_of_shloka(text):
                new_style = "Перевод шлоки"
                confidence = "high"
                reason = "after-shloka-quoted-russian"
            elif prev_assigned in {"Шлока", "Шлока в цитате"} and looks_like_visual_shloka(para):
                new_style = prev_assigned
                confidence = "high"
                reason = "continued-shloka-block"
            elif prev_assigned in {"Цитата 1", "Цитата 2"} and looks_like_visual_quote(para):
                new_style = prev_assigned
                confidence = "medium"
                reason = "continued-quote-block"
            elif looks_like_quote(text) and (
                looks_like_source(next_text)
                or looks_like_source(next_next_text)
                or prev_prev_assigned == "Источник"
            ):
                new_style = "Цитата 1"
                confidence = "medium"
                reason = "quoted-block-near-source"

        if new_style:
            decision = Decision(
                index=para.index,
                text=clean_text(text),
                old_style=style,
                new_style=new_style,
                confidence=confidence or "medium",
                reason=reason or "heuristic",
                applied=True,
            )
            applied.append(decision)
            assigned_styles[i + 1] = new_style
        elif transliteration_score(text) >= 2 or looks_like_quote(text):
            review.append(
                Decision(
                    index=para.index,
                    text=clean_text(text),
                    old_style=style,
                    new_style=None,
                    confidence="low",
                    reason="possible-semantic-style-needs-review",
                    applied=False,
                )
            )
        elif para.is_visual_block or para.paragraph_italic:
            review.append(
                Decision(
                    index=para.index,
                    text=clean_text(text),
                    old_style=style,
                    new_style=None,
                    confidence="low",
                    reason="visual-block-or-paragraph-italic-needs-review",
                    applied=False,
                )
            )

    return applied, review


def export_hints_template(
    src: Path,
    out: Path,
    hint_rules: Optional[Sequence[HintRule]] = None,
) -> dict:
    with zipfile.ZipFile(src, "r") as zin:
        styles_root = load_styles_root(zin)
        catalog = StyleCatalog(styles_root)
        default_paragraph_name = catalog.default_style_name("paragraph")
        document_root = etree.fromstring(zin.read("word/document.xml"))
        paragraphs = iter_paragraphs(document_root)
        for para in paragraphs:
            para.style_name = get_paragraph_style_name(para.node, catalog, default_paragraph_name)

    applied, review = classify_paragraphs(paragraphs, hint_rules=hint_rules)
    candidates = []
    seen = set()
    for item in applied + review:
        if item.index in seen:
            continue
        seen.add(item.index)
        candidates.append(
            {
                "match": {"type": "index", "value": item.index},
                "action": "review_only",
                "style": item.new_style,
                "note": f"current:{item.reason}",
                "text": item.text,
                "old_style": item.old_style,
                "current_confidence": item.confidence,
            }
        )

    template = {
        "input": str(src),
        "rules": candidates,
    }
    out.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"input": str(src), "output": str(out), "candidates": len(candidates)}


def write_report_md(path: Path, summary: dict) -> None:
    lines = []
    lines.append("# Semantic Style Classifier\n")
    lines.append(f"Input: `{summary['input']}`\n")
    lines.append(f"Output: `{summary['output']}`\n")
    lines.append("## Applied\n")
    lines.append(f"- count: {len(summary['applied'])}\n")
    for item in summary["applied"][:200]:
        lines.append(
            f"- #{item['index']} `{item['old_style']}` -> `{item['new_style']}` [{item['confidence']}] "
            f"{item['reason']}: `{item['text'][:160]}`\n"
        )
    hidden = len(summary["applied"]) - min(200, len(summary["applied"]))
    if hidden > 0:
        lines.append(f"- ... {hidden} more applied changes omitted\n")

    lines.append("## Review Candidates\n")
    lines.append(f"- count: {len(summary['review'])}\n")
    for item in summary["review"][:200]:
        lines.append(
            f"- #{item['index']} `{item['old_style']}` [{item['confidence']}] "
            f"{item['reason']}: `{item['text'][:160]}`\n"
        )
    hidden = len(summary["review"]) - min(200, len(summary["review"]))
    if hidden > 0:
        lines.append(f"- ... {hidden} more review candidates omitted\n")

    path.write_text("".join(lines), encoding="utf-8")


def classify_docx(
    src: Path,
    out: Path,
    report_md: Optional[Path],
    report_json: Optional[Path],
    hint_rules: Optional[Sequence[HintRule]] = None,
) -> dict:
    with zipfile.ZipFile(src, "r") as zin:
        styles_root = load_styles_root(zin)
        catalog = StyleCatalog(styles_root)
        canonical_ids = ensure_canonical_styles(catalog)
        default_paragraph_name = catalog.default_style_name("paragraph")

        document_root = etree.fromstring(zin.read("word/document.xml"))
        paragraphs = iter_paragraphs(document_root)
        for para in paragraphs:
            para.style_name = get_paragraph_style_name(para.node, catalog, default_paragraph_name)

        applied, review = classify_paragraphs(paragraphs, hint_rules=hint_rules)
        para_by_index = {p.index: p for p in paragraphs}
        for decision in applied:
            para = para_by_index[decision.index]
            set_paragraph_style(para.node, canonical_ids[decision.new_style])

        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(src, "r") as zin2, zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for info in zin2.infolist():
                data = zin2.read(info.filename)
                if info.filename == "word/styles.xml":
                    zout.writestr(info, etree.tostring(styles_root, xml_declaration=True, encoding="UTF-8", standalone="yes"))
                elif info.filename == "word/document.xml":
                    zout.writestr(info, etree.tostring(document_root, xml_declaration=True, encoding="UTF-8", standalone="yes"))
                else:
                    zout.writestr(info, data)

    summary = {
        "input": str(src),
        "output": str(out),
        "applied": [asdict(x) for x in applied],
        "review": [asdict(x) for x in review],
    }
    if report_json:
        report_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if report_md:
        write_report_md(report_md, summary)
    return summary


def cmd_classify(args) -> None:
    src, temp_dir = resolve_source(Path(args.input))
    out = Path(args.output)
    try:
        hint_rules = load_hints(Path(args.hints_json)) if args.hints_json else []
        summary = classify_docx(
            src,
            out,
            report_md=Path(args.report_md) if args.report_md else None,
            report_json=Path(args.report_json) if args.report_json else None,
            hint_rules=hint_rules,
        )
        print(f"Classified: {summary['input']} -> {summary['output']}")
        print(f"Applied changes: {len(summary['applied'])}")
        print(f"Review candidates: {len(summary['review'])}")
    finally:
        cleanup_temp(temp_dir)


def cmd_export_hints_template(args) -> None:
    src, temp_dir = resolve_source(Path(args.input))
    out = Path(args.output)
    try:
        hint_rules = load_hints(Path(args.hints_json)) if args.hints_json else []
        summary = export_hints_template(src, out, hint_rules=hint_rules)
        print(f"Hints template: {summary['input']} -> {summary['output']}")
        print(f"Candidates: {summary['candidates']}")
    finally:
        cleanup_temp(temp_dir)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Heuristic semantic paragraph style classifier for DOCX")
    sub = p.add_subparsers(dest="cmd", required=True)

    classify = sub.add_parser("classify")
    classify.add_argument("input")
    classify.add_argument("output")
    classify.add_argument("--report-md")
    classify.add_argument("--report-json")
    classify.add_argument("--hints-json")

    hints = sub.add_parser("export-hints-template")
    hints.add_argument("input")
    hints.add_argument("output")
    hints.add_argument("--hints-json")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.cmd == "classify":
        cmd_classify(args)
    elif args.cmd == "export-hints-template":
        cmd_export_hints_template(args)
    else:
        parser.error(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
