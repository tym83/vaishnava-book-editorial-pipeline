#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""
Semantic footnote classifier for DOCX files.

Working semantic map:
- Сноска 1: explanatory / glossary / contextual note
- Сноска 2: source / bibliographic / scripture reference
- Сноска 3: translator note
- Сноска 4: cross-reference / editorial linkage to another place in the book/corpus

Examples:
  python3 docx_footnote_classifier.py classify in.docx out.docx
  python3 docx_footnote_classifier.py classify in.docx out.docx --report-md report.md --report-json report.json
  python3 docx_footnote_classifier.py export-hints-template in.docx hints.json
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


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
W = f"{{{W_NS}}}"

CANONICAL_FOOTNOTE_STYLES = [
    "Сноска 1",
    "Сноска 2",
    "Сноска 3",
    "Сноска 4",
]

TRANSLATOR_NOTE_PATTERN = re.compile(r"(?i)\bприм\.\s*переводчика\b")
EDITOR_NOTE_PATTERN = re.compile(r"(?i)\bприм\.\s*ред\.")
SCRIPTURE_REF_PATTERN = re.compile(
    r"(?i)^\s*(см\.\s*)?("
    r"шб|бг|чч|ав|SB|Bg|Cc|"
    r"ади-лила|мадхья-лила|антья-лила|"
    r"гауд[иӣ]я|гауд[иӣ]я\s+прабандха|"
    r"пл|нп"
    r")\b"
)
SOURCE_ABBREV_REF_PATTERN = re.compile(
    r"(?i)^\s*[А-ЯЁA-Z]{1,5}[А-ЯЁA-Zа-яёa-z]{0,4}(?:\s+[А-ЯЁA-Z]{1,5}[А-ЯЁA-Zа-яёa-z]{0,4})?\s+\d"
)
LETTER_LECTURE_REF_PATTERN = re.compile(
    r"(?i)^\s*(письмо|лекци[яи])\s*\("
)
PURE_CITATION_PATTERN = re.compile(
    r"(?i)^\s*(«[^»]+»|\"[^\"]+\")(\s+из\s+книги)?[^\n]*\b(том|глава|стр\.|комментарий|\d+\.\d+|\d+-\d+)\b"
)
SOURCE_SHAPE_PATTERN = re.compile(
    r"(?i)\b(том|глава|стр\.|комментарий|из перевода|из книги|газет[аы]|журнал[аы])\b"
)
SOURCE_SENTENCE_PATTERN = re.compile(
    r"(?i)^\s*("
    r"эта\s+(лекция|цитата|беседа)\b|"
    r"этот\s+отрывок\s+содержитс\w*\b|"
    r"комментари[ий]+\s+к\b|"
    r"из\s+комментари[яея]\b|"
    r"предыдущ\w+\s+\w+\s+абзац\w*\s+взят\w*"
    r")"
)
CROSSREF_PATTERN = re.compile(
    r"(?i)\b("
    r"см\.|смотри|подробн\w+|объяснени\w+.*см\.|доступн\w+|"
    r"основан[оы]?\s+на|привед(ен|ено|ены|ена)|привод\w+|описан\w*|"
    r"в томе\s+\d|в главе|выше|ниже|по аналогичной схеме"
    r")\b"
)


@dataclass
class HintRule:
    match_type: str
    value: object
    action: str
    style: Optional[str]
    note: str = ""


@dataclass
class FootnoteInfo:
    footnote_id: str
    text: str
    old_styles: List[str]
    paragraphs: List[etree._Element]


@dataclass
class Decision:
    footnote_id: str
    text: str
    old_styles: List[str]
    new_style: Optional[str]
    class_name: Optional[str]
    confidence: str
    reason: str
    applied: bool


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def clean_text(text: str) -> str:
    return " ".join(text.replace("\u00a0", " ").strip().split())


def normalize_text(text: str) -> str:
    text = clean_text(text)
    text = text.replace("ё", "е").replace("Ё", "Е")
    return text.casefold()


def convert_doc_to_docx(path: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="docx-footnote-classifier-"))
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
        die("docx_footnote_classifier currently supports .docx and .doc")
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


def hint_for_footnote(note: FootnoteInfo, rules: Sequence[HintRule]) -> Optional[HintRule]:
    norm_text = normalize_text(note.text)
    for rule in rules:
        if rule.match_type == "id" and str(note.footnote_id) == str(rule.value):
            return rule
        if rule.match_type == "text" and norm_text == normalize_text(str(rule.value)):
            return rule
        if rule.match_type == "regex" and re.search(str(rule.value), note.text):
            return rule
    return None


def ensure_canonical_styles(catalog: StyleCatalog) -> Dict[str, str]:
    style_ids: Dict[str, str] = {}
    for name in CANONICAL_FOOTNOTE_STYLES:
        style_ids[name] = catalog.ensure_style(name, "paragraph", base_name="footnote text")
    return style_ids


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


def iter_footnotes(root, catalog: StyleCatalog, default_name: Optional[str]) -> List[FootnoteInfo]:
    notes: List[FootnoteInfo] = []
    for fn in root.xpath(".//w:footnote[not(@w:type)]", namespaces=NS):
        fid = fn.get(f"{W}id") or ""
        paras: List[etree._Element] = []
        texts: List[str] = []
        styles: List[str] = []
        for para in fn.findall("w:p", namespaces=NS):
            text = "".join(t.text or "" for t in para.findall(".//w:t", namespaces=NS)).strip()
            if text:
                paras.append(para)
                texts.append(text)
                styles.append(get_paragraph_style_name(para, catalog, default_name) or "")
        if texts:
            notes.append(FootnoteInfo(footnote_id=fid, text=" | ".join(texts), old_styles=styles, paragraphs=paras))
    return notes


def looks_like_translator_note(text: str) -> bool:
    return bool(TRANSLATOR_NOTE_PATTERN.search(clean_text(text)))


def looks_like_pure_source_reference(text: str) -> bool:
    t = clean_text(text)
    if not t:
        return False
    if SOURCE_SENTENCE_PATTERN.search(t) and re.search(r"\d", t):
        return True
    if SOURCE_ABBREV_REF_PATTERN.search(t):
        return True
    if LETTER_LECTURE_REF_PATTERN.search(t) and re.search(r"\d", t):
        return True
    if SCRIPTURE_REF_PATTERN.search(t) and len(t.split()) <= 18:
        return True
    if PURE_CITATION_PATTERN.search(t) and len(t.split()) <= 30:
        return True
    if SOURCE_SHAPE_PATTERN.search(t) and len(t.split()) <= 20 and re.search(r"\d", t):
        return True
    if t.startswith("«") and re.search(r"\d", t) and len(t.split()) <= 10:
        return True
    return False


def looks_like_cross_reference(text: str) -> bool:
    t = clean_text(text)
    if not t:
        return False
    if EDITOR_NOTE_PATTERN.search(t):
        return True
    return bool(CROSSREF_PATTERN.search(t))


def infer_class(text: str) -> tuple[str, str, str]:
    t = clean_text(text)
    if looks_like_translator_note(t):
        return ("Сноска 3", "translator_note", "explicit-translator-note")
    if looks_like_cross_reference(t):
        return ("Сноска 4", "cross_reference", "cross-reference-pattern")
    if looks_like_pure_source_reference(t):
        return ("Сноска 2", "source_reference", "source-reference-pattern")
    return ("Сноска 1", "explanatory_note", "default-explanatory")


def needs_review(text: str, style: str) -> bool:
    if style != "Сноска 1":
        return False
    t = clean_text(text)
    if len(t.split()) <= 3:
        return True
    if "|" in t and re.search(r"\d", t):
        return True
    if (
        re.search(r"\b(ШБ|БГ|Чч|Ав|Гв|Сдж|ШБТ|УШЧ|Патр)\b", t, flags=re.IGNORECASE)
        and re.search(r"\d", t)
    ):
        return True
    return False


def classify_footnotes(notes: Sequence[FootnoteInfo], hint_rules: Optional[Sequence[HintRule]] = None) -> tuple[List[Decision], List[Decision]]:
    applied: List[Decision] = []
    review: List[Decision] = []
    hint_rules = hint_rules or []

    for note in notes:
        hint = hint_for_footnote(note, hint_rules)
        if hint is not None:
            if hint.action == "ignore":
                continue
            if hint.action == "review_only":
                review.append(
                    Decision(
                        footnote_id=note.footnote_id,
                        text=clean_text(note.text),
                        old_styles=note.old_styles,
                        new_style=hint.style,
                        class_name=None,
                        confidence="hint",
                        reason=f"hint:{hint.note or hint.match_type}",
                        applied=False,
                    )
                )
                continue
            if hint.action == "set_style" and hint.style:
                applied.append(
                    Decision(
                        footnote_id=note.footnote_id,
                        text=clean_text(note.text),
                        old_styles=note.old_styles,
                        new_style=hint.style,
                        class_name="hint",
                        confidence="hint",
                        reason=f"hint:{hint.note or hint.match_type}",
                        applied=True,
                    )
                )
                continue

        new_style, class_name, reason = infer_class(note.text)
        confidence = "high" if new_style in {"Сноска 2", "Сноска 3"} else "medium"
        applied.append(
            Decision(
                footnote_id=note.footnote_id,
                text=clean_text(note.text),
                old_styles=note.old_styles,
                new_style=new_style,
                class_name=class_name,
                confidence=confidence,
                reason=reason,
                applied=True,
            )
        )
        if needs_review(note.text, new_style):
            review.append(
                Decision(
                    footnote_id=note.footnote_id,
                    text=clean_text(note.text),
                    old_styles=note.old_styles,
                    new_style=new_style,
                    class_name=class_name,
                    confidence="low",
                    reason="ambiguous-explanatory-review",
                    applied=False,
                )
            )
    return applied, review


def export_hints_template(src: Path, out: Path, hint_rules: Optional[Sequence[HintRule]] = None) -> dict:
    with zipfile.ZipFile(src, "r") as zin:
        styles_root = etree.fromstring(zin.read("word/styles.xml"))
        catalog = StyleCatalog(styles_root)
        default_name = catalog.default_style_name("paragraph")
        foot_root = etree.fromstring(zin.read("word/footnotes.xml"))
        notes = iter_footnotes(foot_root, catalog, default_name)
    applied, review = classify_footnotes(notes, hint_rules=hint_rules)
    candidates = []
    seen = set()
    for item in applied + review:
        if item.footnote_id in seen:
            continue
        seen.add(item.footnote_id)
        candidates.append(
            {
                "match": {"type": "id", "value": item.footnote_id},
                "action": "review_only",
                "style": item.new_style,
                "note": f"current:{item.reason}",
                "text": item.text,
                "old_styles": item.old_styles,
                "current_confidence": item.confidence,
            }
        )
    template = {"input": str(src), "rules": candidates}
    out.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"input": str(src), "output": str(out), "candidates": len(candidates)}


def write_report_md(path: Path, summary: dict) -> None:
    lines = []
    lines.append("# Footnote Classifier\n\n")
    lines.append(f"Input: `{summary['input']}`\n\n")
    lines.append(f"Output: `{summary['output']}`\n\n")
    lines.append("## Counts by style\n\n")
    for key, value in sorted(summary["counts_by_style"].items()):
        lines.append(f"- `{key}`: {value}\n")
    lines.append("\n## Applied\n\n")
    for item in summary["applied"][:200]:
        lines.append(
            f"- footnote `{item['footnote_id']}` {item['old_styles']} -> `{item['new_style']}` "
            f"[{item['confidence']}] {item['reason']}: `{item['text'][:180]}`\n"
        )
    hidden = len(summary["applied"]) - min(200, len(summary["applied"]))
    if hidden > 0:
        lines.append(f"- ... {hidden} more applied changes omitted\n")
    lines.append("\n## Review\n\n")
    for item in summary["review"][:200]:
        lines.append(
            f"- footnote `{item['footnote_id']}` -> `{item['new_style']}` "
            f"[{item['confidence']}] {item['reason']}: `{item['text'][:180]}`\n"
        )
    hidden = len(summary["review"]) - min(200, len(summary["review"]))
    if hidden > 0:
        lines.append(f"- ... {hidden} more review items omitted\n")
    path.write_text("".join(lines), encoding="utf-8")


def classify_docx(
    src: Path,
    out: Path,
    report_md: Optional[Path],
    report_json: Optional[Path],
    hint_rules: Optional[Sequence[HintRule]] = None,
) -> dict:
    with zipfile.ZipFile(src, "r") as zin:
        styles_root = etree.fromstring(zin.read("word/styles.xml"))
        catalog = StyleCatalog(styles_root)
        canonical_ids = ensure_canonical_styles(catalog)
        default_name = catalog.default_style_name("paragraph")
        foot_root = etree.fromstring(zin.read("word/footnotes.xml"))
        notes = iter_footnotes(foot_root, catalog, default_name)
        applied, review = classify_footnotes(notes, hint_rules=hint_rules)

        note_by_id = {n.footnote_id: n for n in notes}
        for item in applied:
            if not item.new_style:
                continue
            style_id = canonical_ids[item.new_style]
            note = note_by_id.get(item.footnote_id)
            if note is None:
                continue
            for para in note.paragraphs:
                set_paragraph_style(para, style_id)

        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                data = zin.read(info.filename)
                if info.filename == "word/footnotes.xml":
                    data = etree.tostring(foot_root, encoding="utf-8", xml_declaration=True, standalone="yes")
                elif info.filename == "word/styles.xml":
                    data = etree.tostring(styles_root, encoding="utf-8", xml_declaration=True, standalone="yes")
                zout.writestr(info, data)

    counts_by_style: Dict[str, int] = {}
    for item in applied:
        counts_by_style[item.new_style or "NONE"] = counts_by_style.get(item.new_style or "NONE", 0) + 1
    summary = {
        "input": str(src),
        "output": str(out),
        "counts_by_style": counts_by_style,
        "applied": [asdict(x) for x in applied],
        "review": [asdict(x) for x in review],
    }
    if report_json:
        report_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if report_md:
        write_report_md(report_md, summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Classify DOCX footnotes into canonical footnote styles")
    sub = parser.add_subparsers(dest="command", required=True)

    p_classify = sub.add_parser("classify", help="classify footnotes and write a new docx")
    p_classify.add_argument("input", help="input .docx or .doc")
    p_classify.add_argument("output", help="output .docx")
    p_classify.add_argument("--report-md", help="optional markdown report path")
    p_classify.add_argument("--report-json", help="optional json report path")
    p_classify.add_argument("--hints-json", help="optional hints json path")

    p_hints = sub.add_parser("export-hints-template", help="export review template for manual footnote hints")
    p_hints.add_argument("input", help="input .docx or .doc")
    p_hints.add_argument("output", help="output hints .json")
    p_hints.add_argument("--hints-json", help="optional existing hints json path")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    src, temp_dir = resolve_source(Path(args.input))
    try:
        hint_rules = load_hints(Path(args.hints_json)) if getattr(args, "hints_json", None) else []
        if args.command == "classify":
            summary = classify_docx(
                src,
                Path(args.output),
                report_md=Path(args.report_md) if args.report_md else None,
                report_json=Path(args.report_json) if args.report_json else None,
                hint_rules=hint_rules,
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0
        if args.command == "export-hints-template":
            summary = export_hints_template(
                src,
                Path(args.output),
                hint_rules=hint_rules,
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0
        parser.error("Unknown command")
        return 2
    finally:
        cleanup_temp(temp_dir)


if __name__ == "__main__":
    raise SystemExit(main())
