#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Build a DOCX issue bundle from the current Vibhava Tom 1 translation review.

This is intentionally project-specific.  It turns reviewed findings into
paragraph-anchored issues that can be applied as Word comments to the complete
book copy.  Baseline pilot findings live in this file; expanded pass findings
live in ``docs/vibhava_tom1_review_findings_extra.json`` so editorial feedback
can be diffed and reused across reruns.
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

from lxml import etree

from review_issue_utils import build_issue, clean_text, empty_bundle, write_json


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
W = f"{{{W_NS}}}"


@dataclass(frozen=True)
class Paragraph:
    index: int
    text: str
    norm: str


@dataclass(frozen=True)
class ReviewFinding:
    issue_id: str
    section: str
    anchor: str
    title: str
    message: str
    suggestion: str
    severity: str = "warning"
    kind: str = "translation_review"
    match_mode: str = "contains"
    occurrence: str = "first"


SOURCE_REPORTS = [
    "/home/tym83/Загрузки/Служение/Automate/output/vibhava_tom1_translation_review/ai_review_pilot_001_005.md",
    "/home/tym83/Загрузки/Служение/Automate/output/vibhava_tom1_translation_review/ai_review_tail_081_084.md",
    "/home/tym83/Загрузки/Служение/Automate/output/vibhava_tom1_translation_review/review_packs_84/index.md",
]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTRA_FINDINGS_PATHS = [
    PROJECT_ROOT / "docs" / "vibhava_tom1_review_findings_extra.json",
    PROJECT_ROOT / "docs" / "vibhava_tom1_review_findings_deep_prose.json",
]


FINDINGS: Sequence[ReviewFinding] = [
    ReviewFinding(
        "vibhava-tr-001-001",
        "001",
        "«Гармонизатор» 31.487",
        "Проверить перевод названия периодического издания",
        "`Harmonist` переведён как `Гармонизатор`. Названия периодических изданий обычно сохраняем в оригинале, если нет утверждённого русского названия.",
        "Использовать `Harmonist` / `The Harmonist` либо зафиксировать отдельное глоссарное решение.",
        kind="terminology_title",
    ),
    ReviewFinding(
        "vibhava-tr-001-002",
        "001",
        "«Гаудия» 3.27.8-13",
        "Проверить формат `vol.`",
        "`vol.` передано как `подш.`; это неочевидная и нестандартная форма для читателя.",
        "Выбрать единый формат, например `т.` или `том`, и применить к ссылкам `Гаудия`.",
        kind="reference_format",
    ),
    ReviewFinding(
        "vibhava-tr-001-003",
        "001",
        "Чч 3.2.75,77-80:«Шри Чайтанья-чаритамрита»",
        "Исправить пробелы и пунктуацию в ссылке",
        "В ссылке не хватает пробела после запятой и после двоеточия.",
        "Пример: `Чч 3.2.75, 77-80: «Шри Чайтанья-чаритамрита»...`.",
        severity="info",
        kind="typography",
    ),
    ReviewFinding(
        "vibhava-tr-002-001",
        "002",
        "Имея все благословения Шримати Радхарани",
        "Смысл `dayita` передан неверно",
        "`As one who is cherished by Śrīmatī Rādhārāṇī` означает `дорогой/возлюбленный Шримати Радхарани`, а не `имеющий все благословения`.",
        "Заменить на форму типа `Будучи дорогим Шримати Радхарани...` с учётом глоссария.",
        kind="semantic_error",
    ),
    ReviewFinding(
        "vibhava-tr-002-002",
        "002",
        "чьё явление в этом мире (бху-тале) подобно явлению Верховного Господа Вишну",
        "Смысл `viṣṇu-pāda` смещён",
        "Источник говорит о положении/статусе, а не о подобии явления.",
        "Передать ближе к авторскому глоссу: `занимает то же положение, что и Верховный Господь Вишну`.",
        kind="semantic_error",
    ),
    ReviewFinding(
        "vibhava-tr-002-003",
        "002",
        "Он указал на суть учения Господа Чайтанйи",
        "Уточнить подлежащее",
        "В английском подлежащее здесь Śrīla Rūpa Gosvāmī; в русском `Он` читается как Śrīla Bhaktisiddhānta Sarasvatī.",
        "Сделать подлежащее явным: `Шрила Рупа Госвами изложил суть...`.",
        kind="semantic_error",
    ),
    ReviewFinding(
        "vibhava-tr-002-004",
        "002",
        "лишь шуддха-бхакти, свободное от любых корыстных желаний",
        "Проверить определение `śuddha-bhakti`",
        "Английский текст определяет śuddha-bhakti как благоприятное служение Кришне, свободное от личных желаний; русская конструкция меняет логику определения.",
        "Переформулировать: `определив шуддха-бхакти как благоприятное служение Кришне, свободное от...`.",
        kind="semantic_error",
    ),
    ReviewFinding(
        "vibhava-tr-002-005",
        "002",
        "могущественный защитник (дайи прабху)",
        "Проверить `deliverer / dāyī prabhu`",
        "Источник говорит о том, кто даёт/передаёт знание, а не о `защитнике`.",
        "Заменить на `могущественный дарующий/передающий подлинное знание...`.",
        kind="term_mismatch",
    ),
    ReviewFinding(
        "vibhava-tr-003-001",
        "003",
        "Закончив эту объёмную работу",
        "Проверить авторскую временную перспективу",
        "В источнике `I have undertaken the inditement of this book`; русский вариант звучит так, будто работа уже завершена.",
        "Если не нужна сознательная адаптация перспективы, заменить на формулировку о начале/принятии на себя труда.",
        severity="info",
        kind="style_semantic",
    ),
    ReviewFinding(
        "vibhava-tr-004-001",
        "004",
        "Его вклад значительно увеличил объём этой книги",
        "Неверный перевод `meliorated`",
        "`meliorated` означает `улучшил`, а не `увеличил объём`.",
        "Заменить на `Его вклад значительно улучшил эту разрастающуюся книгу` или близкий вариант.",
        kind="semantic_error",
    ),
    ReviewFinding(
        "vibhava-tr-004-002",
        "004",
        "в конце 1970-80-х",
        "Уточнить период",
        "Источник: `during the late 1970s and throughout the 1980s`; русский вариант теряет `throughout the 1980s`.",
        "Заменить на `в конце 1970-х и на протяжении 1980-х годов`.",
        kind="precision",
    ),
    ReviewFinding(
        "vibhava-tr-004-003",
        "004",
        "Чтобы найти учеников-домохозяев Шрилы Сарасвати Тхакура",
        "Возможен пропуск детали",
        "В источнике есть деталь `including some remote spots and dead ends`; в русском она опущена.",
        "Вернуть деталь, если сохраняем авторскую повествовательную фактуру.",
        severity="info",
        kind="minor_omission",
    ),
    ReviewFinding(
        "vibhava-tr-004-004",
        "004",
        "Но если они и не поймут моих слов",
        "Проверить полемический оттенок",
        "Английская фраза сохраняет иронию: удовлетворительно, что такие люди не могут войти в эти темы. Русский вариант смещает акцент на радость от обсуждения.",
        "Сохранить более острый авторский полемический оттенок.",
        kind="tone_shift",
    ),
    ReviewFinding(
        "vibhava-tr-005-001",
        "005",
        "информации, идущей вразрез с цензурой",
        "Неверный перевод `uncensored broadcasting`",
        "Источник говорит о распространении без цензуры/сдержанности, а не об информации, противоречащей цензуре.",
        "Заменить на `неограниченное/неприкрытое распространение такой неприятной информации`.",
        kind="semantic_error",
    ),
    ReviewFinding(
        "vibhava-tr-005-002",
        "005",
        "риску попасть в немилость к нашим учителям",
        "Смысл просьбы Śānta Mahārāja смещён",
        "Источник: риск стремления к исторической точности неоправдан, если это хотя бы немного беспокоит гуру. Русский вариант делает акцент на личном риске автора.",
        "Передать ближе: `риск стремления к исторической точности неоправдан, если из-за этого наши гуру будут хотя бы немного обеспокоены`.",
        kind="semantic_error",
    ),
    ReviewFinding(
        "vibhava-tr-005-003",
        "005",
        "их ученики, несомненно, огорчаться",
        "Опечатка",
        "`огорчаться` здесь должно быть формой будущего времени.",
        "Исправить на `огорчатся`.",
        severity="info",
        kind="typo",
    ),
    ReviewFinding(
        "vibhava-tr-005-004",
        "005",
        "жалобам их подопечных по поводу этих порицаний нет оправдания",
        "Неверно передано `harp on such criticism`",
        "Источник означает, что последователям нет оправдания постоянно повторять/муссировать такую критику.",
        "Заменить на `их последователям нет оправдания постоянно возвращаться к такой критике`.",
        kind="semantic_error",
    ),
    ReviewFinding(
        "vibhava-tr-005-005",
        "005",
        "не с позиции этического арбитра",
        "Неверно передан термин `etic`",
        "`etic` означает внешнюю исследовательскую позицию, а не этический арбитраж.",
        "Заменить на `не с якобы беспристрастной внешней исследовательской позиции`.",
        kind="term_mismatch",
    ),
    ReviewFinding(
        "vibhava-tr-005-006",
        "005",
        "она основана на священных писаниях",
        "Смысл `original sources` сужен",
        "Источник говорит `directly extracted from original sources`, не обязательно о шастрах.",
        "Заменить на `напрямую взята из первоисточников`.",
        kind="semantic_error",
    ),
    ReviewFinding(
        "vibhava-tr-005-007",
        "005",
        "руководствуясь лишь религиозными соображениями",
        "Проверить `devotional considerations`",
        "`Религиозные соображения` звучит внешне/секулярно и менее точно, чем devotional.",
        "Заменить на `соображениями преданного служения` или `духовными соображениями`.",
        kind="terminology_tone",
    ),
    ReviewFinding(
        "vibhava-tr-tail-001",
        "081-084",
        "Здоровье",
        "Заголовок оформлен основным текстом",
        "В финальном DOCX этот заголовок находится в основном стиле. Для production он должен быть заголовком соответствующего уровня.",
        "Назначить канонический стиль заголовка, как у соседних разделов.",
        kind="style_structure",
        match_mode="exact",
        occurrence="last",
    ),
    ReviewFinding(
        "vibhava-tr-tail-002",
        "081-084",
        "Другие наставления и истории",
        "Заголовок оформлен основным текстом",
        "В финальном DOCX этот заголовок находится в основном стиле. Для production он должен быть заголовком соответствующего уровня.",
        "Назначить канонический стиль заголовка, как у соседних разделов.",
        kind="style_structure",
        match_mode="exact",
        occurrence="last",
    ),
    ReviewFinding(
        "vibhava-tr-tail-003",
        "081-084",
        "Его вечная форма и внутренний экстаз",
        "Заголовок оформлен основным текстом",
        "В финальном DOCX этот заголовок находится в основном стиле. Для production он должен быть заголовком соответствующего уровня.",
        "Назначить канонический стиль заголовка, как у соседних разделов.",
        kind="style_structure",
        match_mode="exact",
        occurrence="last",
    ),
    ReviewFinding(
        "vibhava-tr-081-001",
        "081",
        "брился и стриг волосы только на Вишварупа Махотсаву",
        "Проверить добавление про стрижку волос",
        "Источник говорит `shaving only`; `и стриг волосы` добавлено переводом.",
        "Убрать добавление или подтвердить как допустимое контекстное расширение.",
        severity="info",
        kind="precision",
    ),
    ReviewFinding(
        "vibhava-tr-083-001",
        "083",
        "У вас нет ни сильного сознания, ни ясной способности проводить различие",
        "Проверить перевод `conscience`",
        "`Conscience` ближе к `совесть`, не `сознание`.",
        "Заменить на `У вас недостаточно сильны совесть и способность различать...`.",
        kind="term_precision",
    ),
    ReviewFinding(
        "vibhava-tr-083-002",
        "083",
        "напиться из только что появившегося озера чаранамриты",
        "Проверить `pool of caraṇāmṛta`",
        "`Pool` здесь не обязательно `озеро`; русский вариант может звучать слишком масштабно.",
        "Рассмотреть `водоём/место с водой/лужица чаранамриты` по контексту.",
        severity="info",
        kind="precision",
    ),
    ReviewFinding(
        "vibhava-tr-083-003",
        "083",
        "“С помощью нама-санкиртаны человек служит",
        "Нормализовать вложенные кавычки",
        "В цитатном блоке остались прямые английские кавычки внутри русской цитаты.",
        "Привести вложенные кавычки к принятому русскому правилу.",
        severity="info",
        kind="typography",
    ),
    ReviewFinding(
        "vibhava-tr-084-001",
        "084",
        "она хочет быть убеждена, что Найана-мани Манджари всегда служит",
        "Неверно передано `ensure`",
        "Источник говорит, что Вимала Манджари обеспечивает/устраивает вечное служение Найана-мани Манджари, а не хочет убедиться, что оно происходит.",
        "Заменить на `сама природа Вималы Манджари состоит в том, чтобы постоянно обеспечивать занятость Найана-мани Манджари в служении...`.",
        kind="semantic_error",
    ),
    ReviewFinding(
        "vibhava-tr-084-002",
        "084",
        "Кришной, являющегося богатством гопи",
        "Грамматика и термин `wealth of the gopīs`",
        "Согласование сломано; смысл лучше передать как `Шри Кришна, сокровище гопи`.",
        "Заменить на `темы о Шри Кришне, сокровище гопи` или близкий вариант.",
        kind="grammar_term",
    ),
    ReviewFinding(
        "vibhava-tr-084-003",
        "084",
        "это всё равно, что видеть (или это способ, дарующий нам право видеть)",
        "Проверить силу утверждения",
        "Источник осторожно говорит `is equivalent to, or the means to acquire eligibility for`; русский вариант звучит грубо и неуклюже.",
        "Передать: `равносильно этому или является средством обрести право увидеть...`.",
        kind="semantic_precision",
    ),
    ReviewFinding(
        "vibhava-tr-084-004",
        "084",
        "Его переживания, испытываемые Радхарани в разлуке с Кришной",
        "Синтаксис и смысл",
        "Источник говорит об отождествлении Чайтаньи Махапрабху с чувствами Радхарани, а не о `Его переживаниях, испытываемых Радхарани`.",
        "Заменить на `когда Его отождествление с чувствами Радхарани в разлуке с Кришной стало предельно глубоким`.",
        kind="semantic_error",
    ),
    ReviewFinding(
        "vibhava-tr-084-005",
        "084",
        "Разрываемой этой дилеммой, он упал в обморок",
        "Грамматическая ошибка",
        "Причастие должно согласовываться с `он`.",
        "Исправить на `Разрываемый этой дилеммой, он упал в обморок`.",
        severity="info",
        kind="grammar",
    ),
]


def load_extra_findings(paths: Sequence[Path] = EXTRA_FINDINGS_PATHS) -> List[ReviewFinding]:
    findings: List[ReviewFinding] = []
    for path in paths:
        if not path.exists():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        for index, item in enumerate(raw, 1):
            try:
                findings.append(
                    ReviewFinding(
                        issue_id=item["issue_id"],
                        section=item["section"],
                        anchor=item["anchor"],
                        title=item["title"],
                        message=item["message"],
                        suggestion=item["suggestion"],
                        severity=item.get("severity", "warning"),
                        kind=item.get("kind", "translation_review"),
                        match_mode=item.get("match_mode", "contains"),
                        occurrence=item.get("occurrence", "first"),
                    )
                )
            except KeyError as exc:
                raise SystemExit(f"ERROR: missing {exc} in {path}:{index}") from exc
    return findings


def visible_text(node) -> str:
    return "".join(t.text or "" for t in node.xpath(".//w:t", namespaces=NS)).strip()


def load_paragraphs(docx_path: Path) -> List[Paragraph]:
    with zipfile.ZipFile(docx_path, "r") as z:
        root = etree.fromstring(z.read("word/document.xml"))
    paragraphs: List[Paragraph] = []
    for idx, para in enumerate(root.xpath(".//w:body//w:p", namespaces=NS), 1):
        text = visible_text(para)
        paragraphs.append(Paragraph(idx, text, clean_text(text).casefold()))
    return paragraphs


def matches(paragraph: Paragraph, finding: ReviewFinding) -> bool:
    needle = clean_text(finding.anchor).casefold()
    if finding.match_mode == "exact":
        return paragraph.norm == needle
    if finding.match_mode == "contains":
        return needle in paragraph.norm
    raise ValueError(f"Unsupported match mode: {finding.match_mode}")


def locate(paragraphs: Sequence[Paragraph], finding: ReviewFinding) -> Paragraph:
    found = [paragraph for paragraph in paragraphs if matches(paragraph, finding)]
    if not found:
        raise SystemExit(f"ERROR: anchor not found for {finding.issue_id}: {finding.anchor}")
    if finding.occurrence == "first":
        return found[0]
    if finding.occurrence == "last":
        return found[-1]
    if finding.occurrence.startswith("#"):
        index = int(finding.occurrence[1:]) - 1
        if index < 0 or index >= len(found):
            raise SystemExit(f"ERROR: occurrence out of range for {finding.issue_id}: {finding.occurrence}")
        return found[index]
    raise ValueError(f"Unsupported occurrence: {finding.occurrence}")


def build_bundle(docx_path: Path, output_path: Path, report_path: Path | None = None) -> dict:
    paragraphs = load_paragraphs(docx_path)
    bundle = empty_bundle(
        target_format="docx",
        target_path=str(docx_path),
        source_reports=SOURCE_REPORTS,
    )
    report_lines = [
        "# Vibhava Review Comment Bundle",
        "",
        f"Target: `{docx_path}`",
        f"Output: `{output_path}`",
        "",
        "| Issue | Section | Paragraph | Title | Anchor excerpt |",
        "|---|---|---:|---|---|",
    ]
    findings = list(FINDINGS) + load_extra_findings()
    for finding in findings:
        paragraph = locate(paragraphs, finding)
        issue = build_issue(
            issue_id=finding.issue_id,
            kind=finding.kind,
            severity=finding.severity,
            title=finding.title,
            message=f"[Section {finding.section}] {finding.message}",
            suggestion=finding.suggestion,
            anchor={
                "part": "word/document.xml",
                "paragraph_index": paragraph.index,
                "story_label": "main_story",
            },
            context={"target_excerpt": paragraph.text[:350]},
            metadata={
                "section": finding.section,
                "anchor_text": finding.anchor,
            },
        )
        bundle["issues"].append(issue)
        report_lines.append(
            f"| `{finding.issue_id}` | {finding.section} | {paragraph.index} | {finding.title} | {clean_text(paragraph.text)[:120]} |"
        )

    write_json(output_path, bundle)
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Vibhava Tom 1 review issue bundle for Word comments")
    parser.add_argument("docx")
    parser.add_argument("output_json")
    parser.add_argument("--report-md")
    args = parser.parse_args()
    bundle = build_bundle(Path(args.docx), Path(args.output_json), Path(args.report_md) if args.report_md else None)
    print(json.dumps({"issues": len(bundle["issues"]), "output": args.output_json}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
