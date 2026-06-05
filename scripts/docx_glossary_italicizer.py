#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Apply the canonical ``Char Курсив`` character style to glossary terms.

This is the "apply" counterpart to the ``glossary_expected_italic`` detector in
``docx_style_audit.py``.  It is driven by the same glossary policy CSV and only
acts on entries whose ``italic_automation`` is ``always``.

Safety rules:
- only word forms from ``approved_form`` + ``allowed_forms`` are touched;
- matching uses the same word-boundary semantics as the audit (``\\w`` borders,
  case-insensitive);
- paragraphs in shloka styles are skipped (``--skip-style`` names);
- a match that is already italic is left untouched;
- a match glued into a hyphenated compound (``садху-санга``) is *not* changed and
  is reported instead, so a human can decide;
- a match split across multiple runs is reported, not changed.

The character style is applied through ``w:rStyle`` (a real character style), not
direct ``w:i`` formatting, to stay consistent with the project style rules.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glossary_policy import load_glossary_policy  # noqa: E402

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"w": W_NS}
W = f"{{{W_NS}}}"
XML_SPACE = f"{{{XML_NS}}}space"
DOCX_TEXT_PARTS = ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml")
ITALIC_CHAR_STYLE_NAME = "Char Курсив"


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def convert_doc_to_docx(path: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="docx-italicizer-"))
    subprocess.run(
        ["soffice", "--headless", "--convert-to", "docx", "--outdir", str(temp_dir), str(path)],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    converted = temp_dir / f"{path.stem}.docx"
    if not converted.exists():
        die(f"Could not convert {path} to docx")
    return converted


def resolve_source(path: Path) -> Tuple[Path, Optional[Path]]:
    if not path.exists():
        die(f"Input file not found: {path}")
    if path.suffix.lower() == ".doc":
        converted = convert_doc_to_docx(path)
        return converted, converted.parent
    if path.suffix.lower() != ".docx":
        die("docx_glossary_italicizer supports .docx and .doc")
    return path, None


def cleanup_temp(temp_dir: Optional[Path]) -> None:
    if temp_dir and temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)


def style_name_to_id(styles_root: etree._Element) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for style in styles_root.findall("w:style", NS):
        name_el = style.find("w:name", NS)
        if name_el is None:
            continue
        mapping[name_el.get(W + "val")] = style.get(W + "styleId")
    return mapping


def paragraph_style_id(p: etree._Element) -> Optional[str]:
    el = p.find("w:pPr/w:pStyle", NS)
    return el.get(W + "val") if el is not None else None


def run_style_id(r: etree._Element) -> Optional[str]:
    el = r.find("w:rPr/w:rStyle", NS)
    return el.get(W + "val") if el is not None else None


def run_is_italic(r: etree._Element, italic_style_id: Optional[str]) -> bool:
    if italic_style_id and run_style_id(r) == italic_style_id:
        return True
    rpr = r.find("w:rPr", NS)
    if rpr is None:
        return False
    return rpr.find("w:i", NS) is not None or rpr.find("w:iCs", NS) is not None


def single_text_node(r: etree._Element) -> Optional[etree._Element]:
    texts = r.findall("w:t", NS)
    if len(texts) == 1:
        return texts[0]
    return None


def set_text(node: etree._Element, value: str) -> None:
    node.text = value
    if value != value.strip():
        node.set(XML_SPACE, "preserve")
    else:
        node.attrib.pop(XML_SPACE, None)


def make_run_clone(template: etree._Element, text: str, italic_style_id: Optional[str], italic: bool) -> etree._Element:
    new_r = deepcopy(template)
    for t in new_r.findall("w:t", NS):
        new_r.remove(t)
    rpr = new_r.find("w:rPr", NS)
    if italic:
        if rpr is None:
            rpr = etree.Element(W + "rPr")
            new_r.insert(0, rpr)
        existing = rpr.find("w:rStyle", NS)
        if existing is None:
            existing = etree.Element(W + "rStyle")
            rpr.insert(0, existing)
        existing.set(W + "val", italic_style_id)
    new_t = etree.SubElement(new_r, W + "t")
    set_text(new_t, text)
    return new_r


def build_pattern(forms: List[str]) -> re.Pattern:
    ordered = sorted({f for f in forms if f}, key=len, reverse=True)
    body = "|".join(re.escape(f) for f in ordered)
    return re.compile(rf"(?<!\w)(?:{body})(?!\w)", re.IGNORECASE | re.UNICODE)


def process_paragraph(
    p: etree._Element,
    pattern: re.Pattern,
    italic_style_id: str,
    skip_para_style_ids: set,
    include_compounds: bool,
    stats: Counter,
    samples: Dict[str, List[str]],
) -> None:
    if paragraph_style_id(p) in skip_para_style_ids:
        return

    runs = p.findall(".//w:r", NS)
    spans: List[Tuple[int, int, etree._Element, str]] = []
    full = []
    pos = 0
    for r in runs:
        t = single_text_node(r)
        text = (t.text or "") if t is not None else "".join(n.text or "" for n in r.findall("w:t", NS))
        spans.append((pos, pos + len(text), r, text))
        full.append(text)
        pos += len(text)
    full_text = "".join(full)
    if not full_text:
        return

    def is_token_char(ch: str) -> bool:
        return ch.isalpha() or ch == "-"

    # run_index -> list of local (start, end) intervals to italicize.
    # A single match may distribute intervals over several runs (compound case).
    schedule: Dict[int, List[Tuple[int, int]]] = {}

    for m in pattern.finditer(full_text):
        s, e = m.start(), m.end()
        before = full_text[s - 1] if s > 0 else ""
        after = full_text[e] if e < len(full_text) else ""
        is_compound = before == "-" or after == "-"
        if is_compound:
            if not include_compounds:
                stats["skipped_compound"] += 1
                samples["compound"].append(m.group(0) + " @ …" + full_text[max(0, s - 12):e + 12].strip())
                continue
            # expand to the full hyphenated compound token
            while s > 0 and is_token_char(full_text[s - 1]):
                s -= 1
            while e < len(full_text) and is_token_char(full_text[e]):
                e += 1

        covering = [i for i, (rs, re_, _r, _txt) in enumerate(spans) if rs < e and re_ > s]
        if not covering:
            continue
        applied_any = False
        blocked = False
        for ri in covering:
            rs, re_, r, _txt = spans[ri]
            if single_text_node(r) is None:
                blocked = True
                continue
            if run_is_italic(r, italic_style_id):
                # this slice is already italic — nothing to do, still counts as covered
                applied_any = True
                continue
            ls = max(s, rs) - rs
            le = min(e, re_) - rs
            if le > ls:
                schedule.setdefault(ri, []).append((ls, le))
                applied_any = True
        if applied_any:
            stats["italicized_compounds" if is_compound else "italicized"] += 1
            samples["applied_compound" if is_compound else "applied"].append(full_text[s:e])
        elif blocked:
            stats["skipped_cross_run"] += 1
            samples["cross_run"].append(full_text[s:e])
        else:
            stats["skipped_already_italic"] += 1

    if not schedule:
        return

    for ri, raw_spans in schedule.items():
        rs, re_, r, text = spans[ri]
        # merge overlapping / touching intervals within this run
        raw_spans.sort()
        merged: List[Tuple[int, int]] = []
        for ms, me in raw_spans:
            if merged and ms <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], me))
            else:
                merged.append((ms, me))
        parent = r.getparent()
        index = parent.index(r)
        # Build alternating segments: roman / italic / roman ...
        new_runs: List[etree._Element] = []
        cursor = 0
        for ms, me in merged:
            if ms > cursor:
                new_runs.append(make_run_clone(r, text[cursor:ms], italic_style_id, False))
            new_runs.append(make_run_clone(r, text[ms:me], italic_style_id, True))
            cursor = me
        if cursor < len(text):
            new_runs.append(make_run_clone(r, text[cursor:], italic_style_id, False))
        parent.remove(r)
        for offset, nr in enumerate(new_runs):
            parent.insert(index + offset, nr)


def italicize_docx(
    src: Path,
    out: Path,
    glossary_path: Path,
    entry_ids: Optional[List[str]],
    skip_style_names: List[str],
    include_compounds: bool,
    report_json: Optional[Path],
) -> Dict[str, object]:
    entries = [e for e in load_glossary_policy(glossary_path) if e.italic_automation == "always"]
    if entry_ids:
        wanted = set(entry_ids)
        entries = [e for e in entries if e.entry_id in wanted]
    if not entries:
        die("No matching always-italic glossary entries selected")

    forms: List[str] = []
    used_entries = []
    for e in entries:
        used_entries.append({"id": e.entry_id, "approved_form": e.approved_form, "forms": e.search_forms()})
        forms.extend(e.search_forms())
    pattern = build_pattern(forms)

    stats: Counter = Counter()
    samples: Dict[str, List[str]] = {"applied": [], "applied_compound": [], "compound": [], "cross_run": []}

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src, "r") as zin, zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        # resolve style ids from styles.xml first
        styles_data = zin.read("word/styles.xml")
        styles_root = etree.fromstring(styles_data)
        name_to_id = style_name_to_id(styles_root)
        italic_style_id = name_to_id.get(ITALIC_CHAR_STYLE_NAME)
        if not italic_style_id:
            die(f"Character style '{ITALIC_CHAR_STYLE_NAME}' not found in styles.xml")
        skip_ids = {name_to_id[n] for n in skip_style_names if n in name_to_id}

        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename in DOCX_TEXT_PARTS:
                root = etree.fromstring(data)
                for p in root.findall(".//w:p", NS):
                    process_paragraph(p, pattern, italic_style_id, skip_ids, include_compounds, stats, samples)
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone="yes")
            zout.writestr(info, data)

    summary = {
        "input": str(src),
        "output": str(out),
        "italic_char_style": ITALIC_CHAR_STYLE_NAME,
        "italic_style_id": italic_style_id,
        "skipped_styles": skip_style_names,
        "entries": used_entries,
        "stats": dict(sorted(stats.items())),
        "samples": {k: v[:50] for k, v in samples.items()},
    }
    if report_json:
        report_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def cmd_apply(args) -> None:
    src, temp_dir = resolve_source(Path(args.input))
    try:
        summary = italicize_docx(
            src,
            Path(args.output),
            Path(args.glossary_approved),
            args.entry_id or None,
            args.skip_style,
            args.include_compounds,
            Path(args.report_json) if args.report_json else None,
        )
        s = summary["stats"]
        print(f"Italicized glossary terms: {summary['input']} -> {summary['output']}")
        print(f"Applied standalone (Char Курсив): {s.get('italicized', 0)}")
        print(f"Applied compounds (Char Курсив): {s.get('italicized_compounds', 0)}")
        print(f"Skipped already italic: {s.get('skipped_already_italic', 0)}")
        print(f"Skipped hyphen compounds: {s.get('skipped_compound', 0)}")
        print(f"Skipped split-across-runs: {s.get('skipped_cross_run', 0)}")
    finally:
        cleanup_temp(temp_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply Char Курсив to always-italic glossary terms")
    sub = parser.add_subparsers(dest="cmd", required=True)
    apply_p = sub.add_parser("apply")
    apply_p.add_argument("input")
    apply_p.add_argument("output")
    apply_p.add_argument("--glossary-approved", required=True)
    apply_p.add_argument("--entry-id", action="append", help="restrict to these glossary ids (repeatable)")
    apply_p.add_argument(
        "--skip-style", action="append", default=["Шлока", "Шлока в цитате"],
        help="paragraph style names to skip (default: shloka styles)",
    )
    apply_p.add_argument(
        "--include-compounds", action="store_true",
        help="also italicize the full hyphenated compound when a term is part of one",
    )
    apply_p.add_argument("--report-json")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.cmd == "apply":
        cmd_apply(args)
        return 0
    parser.error(f"Unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
