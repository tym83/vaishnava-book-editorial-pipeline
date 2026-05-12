#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Slice the English SBV PDF text layer into Tom 1 review sections.

This is intentionally project-specific: the source PDF contains all three volumes,
whereas the Russian review split is section-based.  The slicer uses exact heading
lines in sequential order.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional


SECTION_HEADINGS = [
    ("001", "Справочник по ссылкам", "Guide to References"),
    ("002", "Мангалачарана", "Maṅgalācaraṇa"),
    ("003", "От автора", "Author's Submission"),
    ("004", "Предисловие", "Preface"),
    ("005", "Апология", "Apologia"),
    ("006", "Редакторское примечание", "Editorial Notes"),
    ("007", "Номенклатура", "Nomenclature"),
    ("008", "Явление", "Advent"),
    ("009", "Детство и юность", "Childhood and Youth"),
    ("010", "Занятость", "Employment"),
    ("011", "Следование Чатур-масье", "Observance of Cātur-māsya"),
    ("012", "Исследовательская деятельность", "Further Scholarly Activities"),
    ("013", "Посвящение", "Initiation"),
    ("014", "Почтение к Шри Гурудеве", "Regard for Śrī Gurudeva"),
    ("015", "В Пурӣ", "In Purī"),
    ("016", "Последнее сражение на поле джйотиш", "Last Engagement in Jyotiṣa"),
    ("017", "Восточная Бенгалия и Южная Индия", "East Bengal and South India"),
    ("018", "Переезд в Майяпур", "Deputation to Māyāpur"),
    ("019", "Миллиард святых имен", "A Billion Names"),
    ("020", "Лилы со Шри Гурудевой", "Pastimes with Śrī Gurudeva"),
    ("021", "Сражение в Балигхай", "The Bālighāi Showdown"),
    ("022", "Утверждение авторитетности Гаура-бхаджана", "Upholding Gaura-bhajana"),
    ("023", "Кашимбазар Саммиланӣ", "First Kashimbazar Sammilanī"),
    ("024", "Печатный и проповеднический центр", "A Press and a Preaching Center"),
    ("025", "Уход двух ачарьев", "Two Ācāryas Depart"),
    ("026", "Шрила Бхактивинода Тхакур", "Śrīla Bhaktivinoda Ṭhākura"),
    ("027", "Шрила Гаура Кишора дас Бабаджи", "Śrīla Gaura Kiśora dāsa Bābājī"),
    ("028", "Калькутта", "Getting Established in Calcutta"),
    ("029", "Вишва-Вайшнава-раджа Сабха", "The Viśva-Vaiṣṇava-rāja Sabhā"),
    ("030", "Развитие Миссии", "The Mission Unfolds"),
    ("031", "1919 год", "1919"),
    ("032", "1920 год", "1920"),
    ("033", "Первопроходцы Восточной Бенгалии", "Pioneering in East Bengal"),
    ("034", "Период с 1921 по 1923 год", "1921–23"),
    ("035", "Период с 1924 по 1925 год", "1924–25"),
    ("036", "Жестокое нападение", "A Murderous Attack"),
    ("037", "Период с 1926 по 1930 год", "1926–30"),
    ("038", "Период с 1930 по 1933 год", "1930–33"),
    ("039", "Фатовство и праздность", "Foppery and Sloth"),
    ("040", "Соперничество между лидерами", "Executive Rivalry"),
    ("041", "Последние дни", "Last Days"),
    ("042", "Уход", "Disappearance"),
    ("043", "Внешний вид и одежда", "Appearance and Dress"),
    ("044", "Повседневная деятельность", "Daily Activities"),
    ("045", "Эмблема", "Logo"),
    ("046", "Распорядок дня", "Daily Schedule"),
    ("047", "Стандарты Матха", "Maṭha Standards"),
    ("048", "Активность Матхов", "Dynamism of the Maṭhas"),
    ("049", "Пурӣ, 1918 год", "Purī, 1918"),
    ("050", "Северная Индия, 1926-1927 годы", "North India, 1926–27"),
    ("051", "Ассам, 1928 год", "Assam, 1928"),
    ("052", "Южная Индия, 1930-31, 1932 годы", "South India, 1930–31 and 1932"),
    ("053", "Кӣртан", "Kīrtana"),
    ("054", "Джапа", "Japa"),
    ("055", "Хари-катха", "Hari-kathā"),
    ("056", "Трансцендентный подход к священным писаниям", "The Transcendental Approach to Scripture"),
    ("057", "Сравнительная важность различных писаний", "Comparative Importance of Various Writings"),
    ("058", "Стихи", "Verses"),
    ("059", "Теологический вклад", "Theological Contributions"),
    ("060", "Публикация литературы и её распространение", "Publication and Circulation"),
    ("061", "Периодические издания", "Periodicals"),
    ("062", "Содержание и характер статей", "Content and Temper of Articles"),
    ("063", "Трансцендентный корректор", "The Transcendental Proofreader"),
    ("064", "Английский язык", "English"),
    ("065", "Неологизмы", "Neologisms"),
    ("066", "Лингвистическая война", "Linguistic Warfare"),
    ("067", "Шри Навадвипа-дхама", "Śrī Navadvīpa-dhāma"),
    ("068", "Восстановление затерянных святых мест", "Restoring Lost Sites"),
    ("069", "Враджа-мандала", "Vraja-maṇḍala"),
    ("070", "Парикрамы", "Parikramās"),
    ("071", "Игры в Майяпуре", "Māyāpur Pastimes"),
    ("072", "Отношения с мусульманами", "Dealings with Muslims"),
    ("073", "Игры в Пурушоттама-кшетре", "Pastimes in Puruṣottama-kṣetra"),
    ("074", "Алаланатха", "Ālālanātha"),
    ("075", "Слава Курукшетры", "The Glories of Kurukṣetra"),
    ("076", "Арташрам в Алаланатхе", "Ālālanātha Artashram"),
    ("077", "Определение", "Definition"),
    ("078", "Питание", "Diet"),
    ("079", "Избирательность", "Selectiveness"),
    ("080", "Экадаши", "Ekādaśī"),
    ("081", "Чатур-масья и другие обеты", "Cātur-māsya and Other Observances"),
    ("082", "Здоровье", "Health Issues"),
    ("083", "Другие наставления и истории", "Further Instructions and Anecdotes"),
    ("084", "Его вечная форма и внутренний экстаз", "His Eternal Form and Internal Ecstasy"),
]

SENTINEL_HEADING = "Notes"


@dataclass
class HeadingHit:
    code: str
    ru_title: str
    en_title: str
    page: int
    offset: int
    output: Optional[str] = None
    chars: int = 0
    words: int = 0


def normalize_heading(text: str) -> str:
    return " ".join(text.strip().split()).casefold()


def page_offsets(text: str) -> List[int]:
    offsets = [0]
    for match in re.finditer(r"\f", text):
        offsets.append(match.end())
    return offsets


def page_for_offset(offsets: List[int], offset: int) -> int:
    page = 1
    for idx, start in enumerate(offsets, start=1):
        if start <= offset:
            page = idx
        else:
            break
    return page


def find_heading(text: str, offsets: List[int], heading: str, after: int, min_page: int, max_page: int) -> tuple[int, int]:
    wanted = normalize_heading(heading)
    for match in re.finditer(r"^.*$", text, flags=re.MULTILINE):
        if match.start() <= after:
            continue
        page = page_for_offset(offsets, match.start())
        if page < min_page:
            continue
        if page > max_page:
            break
        if normalize_heading(match.group(0)) == wanted:
            return match.start(), page
    raise ValueError(f"Heading not found after offset {after}: {heading}")


def clean_section_text(raw: str) -> str:
    raw = raw.replace("\f", "\n")
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip() + "\n"


def write_index_md(path: Path, hits: List[HeadingHit]) -> None:
    lines = [
        "# Vibhava Tom 1 EN Section Index",
        "",
        "| Code | RU title | EN title | PDF page | Words |",
        "|---|---|---|---:|---:|",
    ]
    for hit in hits:
        lines.append(f"| {hit.code} | {hit.ru_title} | {hit.en_title} | {hit.page} | {hit.words} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def slice_sections(text_path: Path, out_dir: Path, min_page: int, max_page: int) -> dict:
    text = text_path.read_text(encoding="utf-8", errors="replace")
    offsets = page_offsets(text)
    cursor = 0
    hits: List[HeadingHit] = []
    for code, ru_title, en_title in SECTION_HEADINGS:
        offset, page = find_heading(text, offsets, en_title, cursor, min_page, max_page)
        hits.append(HeadingHit(code=code, ru_title=ru_title, en_title=en_title, page=page, offset=offset))
        cursor = offset

    sentinel_offset, sentinel_page = find_heading(text, offsets, SENTINEL_HEADING, cursor, min_page, max_page)
    out_dir.mkdir(parents=True, exist_ok=True)
    for idx, hit in enumerate(hits):
        end = hits[idx + 1].offset if idx + 1 < len(hits) else sentinel_offset
        section = clean_section_text(text[hit.offset:end])
        out = out_dir / f"{hit.code}.txt"
        out.write_text(section, encoding="utf-8")
        hit.output = str(out)
        hit.chars = len(section)
        hit.words = len(section.split())

    summary = {
        "input": str(text_path),
        "output_dir": str(out_dir),
        "sections": [asdict(hit) for hit in hits],
        "sentinel": {"heading": SENTINEL_HEADING, "page": sentinel_page, "offset": sentinel_offset},
    }
    (out_dir / "index.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_index_md(out_dir / "index.md", hits)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Slice English SBV PDF text into Tom 1 sections")
    parser.add_argument("text", help="pdftotext -layout output")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--min-page", type=int, default=20)
    parser.add_argument("--max-page", type=int, default=550)
    args = parser.parse_args()
    summary = slice_sections(Path(args.text), Path(args.output_dir), args.min_page, args.max_page)
    print(f"Wrote {len(summary['sections'])} sections to {summary['output_dir']}")
    print(f"Sentinel {summary['sentinel']['heading']} at PDF page {summary['sentinel']['page']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
