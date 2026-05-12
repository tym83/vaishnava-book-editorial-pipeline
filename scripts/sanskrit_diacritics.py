#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for Sanskrit diacritics in Russian editorial prose."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional


COMBINING_MARKS = "\u0304\u0323\u0307\u0303\u0301"
PRECOMPOSED_DIACRITIC_CHARS = "ĀāĪīŪūṚṛṜṝḶḷḸḹṂṃṀṁṄṅÑñṆṇṬṭḌḍḤḥŚśṢṣ"
DIACRITIC_RE = re.compile(f"[{re.escape(PRECOMPOSED_DIACRITIC_CHARS + COMBINING_MARKS)}]")
WORD_RE = re.compile(
    rf"[A-Za-zА-Яа-яЁё{re.escape(PRECOMPOSED_DIACRITIC_CHARS + COMBINING_MARKS)}]+"
    rf"(?:[-‑][A-Za-zА-Яа-яЁё{re.escape(PRECOMPOSED_DIACRITIC_CHARS + COMBINING_MARKS)}]+)*"
)
PROSE_REFERENCE_RE = re.compile(r"^\s*[A-Za-zА-Яа-яЁё]{1,6}\s*(?:\d[\d.,:;–—-]*)?:")

PRESERVE_DIACRITIC_STYLES = {"Шлока", "Шлока в цитате"}
QUOTE_STYLES = {"Цитата 1", "Цитата 2"}
FOOTNOTE_PROSE_STYLES = {"Сноска", "Сноска 1", "Сноска 2", "Сноска 3", "Сноска 4"}
PROSE_CONTEXT_STYLE_PREFIXES = ("toc", "Заголовок")

RUSSIAN_PROSE_WORDS = {
    "а",
    "без",
    "был",
    "была",
    "были",
    "было",
    "в",
    "во",
    "все",
    "всех",
    "где",
    "для",
    "его",
    "ее",
    "её",
    "если",
    "глава",
    "и",
    "из",
    "или",
    "их",
    "к",
    "как",
    "когда",
    "который",
    "которые",
    "между",
    "на",
    "не",
    "но",
    "о",
    "об",
    "однако",
    "он",
    "она",
    "они",
    "от",
    "по",
    "после",
    "при",
    "с",
    "со",
    "так",
    "также",
    "то",
    "что",
    "чтобы",
    "это",
    "номер",
    "стих",
    "стихи",
    "стр",
    "том",
}

SANSKRIT_VERSE_WORDS = {
    "бху",
    "виджнана",
    "виграхайа",
    "дайине",
    "дайитайа",
    "деве",
    "деви",
    "ити",
    "крпабдхайе",
    "кр̣ш̣н̣а",
    "кришна",
    "нама",
    "намах",
    "намас",
    "намине",
    "намо",
    "ом",
    "прабхаве",
    "сту",
    "тале",
    "те",
}

LONG_COMPOUND_RE = re.compile(r"[-‑].{8,}[-‑]")

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
    "\u0304": "",
    "\u0323": "",
    "\u0307": "",
    "\u0303": "",
    "\u0301": "",
}

POST_DEDIACRITIC_REPLACEMENTS = [
    (r"\bсаннйа", "саннья"),
    (r"\bСаннйа", "Саннья"),
    (r"\bачарйа", "ачарья"),
    (r"\bАчарйа", "Ачарья"),
    (r"\bачарй", "ачарь"),
    (r"\bАчарй", "Ачарь"),
    (r"\bвайрагйа", "вайрагья"),
    (r"\bВайрагйа", "Вайрагья"),
    (r"\bвайрагй", "вайрагь"),
    (r"\bВайрагй", "Вайрагь"),
    (r"\bвидйа", "видья"),
    (r"\bВидйа", "Видья"),
    (r"\bвидй", "видь"),
    (r"\bВидй", "Видь"),
    (r"\bМадхйа", "Мадхья"),
    (r"\bмадхйа", "мадхья"),
    (r"\bАнтйа", "Антья"),
    (r"\bантйа", "антья"),
    (r"\bЧатур-масйа", "Чатур-масья"),
    (r"\bчатур-масйа", "чатур-масья"),
    (r"\bМайапур", "Майяпур"),
    (r"\bмайапур", "майяпур"),
    (r"\bЧатур-масй", "Чатур-мась"),
    (r"\bчатур-масй", "чатур-мась"),
]


@dataclass
class DiacriticStats:
    word_count: int
    marked_word_count: int
    marked_word_ratio: float
    russian_prose_word_count: int
    russian_prose_word_ratio: float
    line_count: int
    has_sentence_punctuation: bool

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class DiacriticDecision:
    action: str
    reason: str
    stats: DiacriticStats

    def to_dict(self) -> Dict[str, object]:
        return {"action": self.action, "reason": self.reason, "stats": self.stats.to_dict()}


def clean_text(text: str) -> str:
    return " ".join(str(text or "").replace("\u00a0", " ").split())


def has_sanskrit_diacritics(text: str) -> bool:
    return DIACRITIC_RE.search(str(text or "")) is not None


def word_has_diacritics(word: str) -> bool:
    return has_sanskrit_diacritics(word)


def diacritic_stats(text: str) -> DiacriticStats:
    raw = str(text or "")
    words = WORD_RE.findall(raw)
    marked = [word for word in words if word_has_diacritics(word)]
    prose_words = [word for word in words if word.casefold().replace("ё", "е") in RUSSIAN_PROSE_WORDS]
    word_count = len(words)
    return DiacriticStats(
        word_count=word_count,
        marked_word_count=len(marked),
        marked_word_ratio=(len(marked) / word_count) if word_count else 0.0,
        russian_prose_word_count=len(prose_words),
        russian_prose_word_ratio=(len(prose_words) / word_count) if word_count else 0.0,
        line_count=max(1, len([line for line in raw.splitlines() if line.strip()])),
        has_sentence_punctuation=bool(re.search(r"[.!?]", raw)),
    )


def match_words(text: str) -> List[str]:
    normalized = dediacritize_text(text).casefold().replace("ё", "е")
    return WORD_RE.findall(normalized)


def verse_signal_count(text: str) -> int:
    words = match_words(text)
    count = 0
    for word in words:
        parts = [word, *re.split(r"[-‑]", word)]
        if any(part in SANSKRIT_VERSE_WORDS for part in parts):
            count += 1
    return count


def has_long_sanskrit_compound(text: str) -> bool:
    return LONG_COMPOUND_RE.search(clean_text(text)) is not None


def looks_like_sanskrit_quote(text: str) -> bool:
    if not has_sanskrit_diacritics(text):
        return False
    stats = diacritic_stats(text)
    if stats.word_count == 0 or stats.word_count > 120:
        return False
    if stats.russian_prose_word_count >= 3 and stats.russian_prose_word_ratio >= 0.12:
        return False
    signal_count = verse_signal_count(text)
    if stats.line_count >= 2 and stats.marked_word_ratio >= 0.30 and stats.russian_prose_word_ratio <= 0.18:
        return True
    if stats.word_count >= 8 and stats.marked_word_ratio >= 0.30 and stats.russian_prose_word_ratio <= 0.18:
        return True
    if (
        stats.word_count >= 4
        and stats.marked_word_ratio >= 0.55
        and stats.russian_prose_word_count == 0
        and re.search(r"[,;।]", text)
    ):
        return True
    if stats.word_count >= 4 and signal_count >= 1 and stats.marked_word_count >= 2 and stats.russian_prose_word_ratio <= 0.18:
        return True
    if stats.word_count <= 3 and has_long_sanskrit_compound(text) and stats.russian_prose_word_count == 0:
        return True
    return False


def looks_like_footnote_sanskrit_block(text: str) -> bool:
    if not looks_like_sanskrit_quote(text):
        return False
    stats = diacritic_stats(text)
    return stats.line_count >= 2 and stats.marked_word_ratio >= 0.40


def classify_diacritic_context(text: str, style_name: Optional[str] = None) -> DiacriticDecision:
    stats = diacritic_stats(text)
    if stats.marked_word_count == 0:
        return DiacriticDecision("none", "no-diacritics", stats)

    style = style_name or ""
    if style in PRESERVE_DIACRITIC_STYLES:
        return DiacriticDecision("preserve", f"style:{style}", stats)
    if any(style.startswith(prefix) for prefix in PROSE_CONTEXT_STYLE_PREFIXES):
        return DiacriticDecision("normalize_prose", f"style:{style}", stats)
    if style in FOOTNOTE_PROSE_STYLES and not looks_like_footnote_sanskrit_block(text):
        return DiacriticDecision("normalize_prose", f"footnote-prose-style:{style}", stats)
    if PROSE_REFERENCE_RE.search(clean_text(text)):
        return DiacriticDecision("normalize_prose", "reference-or-abbreviation-entry", stats)
    if style in QUOTE_STYLES and looks_like_sanskrit_quote(text):
        return DiacriticDecision("preserve", f"quote-style-transliteration:{style}", stats)
    if looks_like_sanskrit_quote(text):
        return DiacriticDecision("preserve", "transliteration-block", stats)
    return DiacriticDecision("normalize_prose", "russian-prose-with-diacritics", stats)


def dediacritize_text(text: str) -> str:
    if not text:
        return text

    out = text
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

    out = unicodedata.normalize("NFD", out)
    for src, dst in COMBINING_MAP.items():
        out = out.replace(src, dst)
    out = unicodedata.normalize("NFC", out)

    for pattern, repl in POST_DEDIACRITIC_REPLACEMENTS:
        out = re.sub(pattern, repl, out)
    return out
