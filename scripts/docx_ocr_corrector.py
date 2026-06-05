#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Corpus-internal OCR detection and reviewed-map correction for a Russian DOCX.

This is deliberately split into two non-destructive steps:

``detect``
    High-precision, corpus-internal proposal builder.  It never edits the file.
    A correction is proposed only when the document's *own* usage backs it up:
    - a hunspell-unknown rare token whose single typical-confusion substitution
      (н↔в↔я↔и, с↔е, ш↔щ ...) lands on a form that is frequent in this document
      or valid Russian -> letter-confusion OCR error;
    - an internal-hyphen token whose de-hyphenated join is frequent in this
      document while the hyphen halves are fragments -> broken line-break hyphen.
    Sanskrit transliteration floods a plain dictionary check with noise, so the
    proposals are meant to be reviewed by a human before ``apply``.

``apply``
    Applies an explicit, human-reviewed ``[{"from": ..., "to": ...}]`` map.
    Whole-token replacement (letter boundaries, internal hyphens allowed) across
    runs, preserving run styles (incl. ``Char Курсив``).  Case of the first
    character is taken from the matched source token, so sentence-start / name
    casing is preserved.  Reports per-correction counts and unmatched entries.

``detect`` needs ``spylls`` and a hunspell dictionary; ``apply`` needs only lxml.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"w": W_NS}
W = f"{{{W_NS}}}"
XML_SPACE = f"{{{XML_NS}}}space"
PARTS = ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml")
LETTER = "А-Яа-яЁёA-Za-z"
WORD_RE = re.compile(r"[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*")
# typical Cyrillic OCR confusion pairs (visually similar glyphs)
CONFUSIONS = [
    ("в", "н"), ("я", "н"), ("н", "в"), ("н", "я"), ("е", "с"), ("с", "е"),
    ("ы", "я"), ("н", "и"), ("и", "н"), ("ш", "щ"), ("р", "в"), ("в", "и"),
]


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_parts_text(path: Path) -> List[str]:
    paras: List[str] = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        for part in PARTS:
            if part not in names:
                continue
            for p in etree.fromstring(z.read(part)).findall(".//w:p", NS):
                paras.append("".join(n.text or "" for n in p.findall(".//w:t", NS)))
    return paras


# --------------------------------------------------------------------------- detect
def cmd_detect(args) -> None:
    try:
        from spylls.hunspell import Dictionary
    except ImportError:
        die("detect needs the 'spylls' package (pip install spylls)")
    dic = Dictionary.from_files(args.dict)

    def valid(w: str) -> bool:
        return dic.lookup(w) or dic.lookup(w.lower()) or dic.lookup(w.capitalize())

    paras = read_parts_text(Path(args.input))
    tokens: List[str] = []
    for tx in paras:
        tokens.extend(WORD_RE.findall(tx))
    freq_plain = Counter(t.lower() for t in tokens if "-" not in t)
    freq_hyph = Counter(t.lower() for t in tokens if "-" in t)

    def context(tok: str) -> str:
        for tx in paras:
            m = re.search(r".{0,30}" + re.escape(tok) + r".{0,30}", tx)
            if m:
                return m.group(0).strip()
        return ""

    proposals: List[Dict[str, object]] = []
    seen = set()

    # A. letter-confusion against a frequent / valid form
    for tok, f in sorted(freq_plain.items()):
        if f > args.max_freq or len(tok) < args.min_len or valid(tok):
            continue
        for i, ch in enumerate(tok):
            done = False
            for a, b in CONFUSIONS:
                if ch != a:
                    continue
                cand = tok[:i] + b + tok[i + 1:]
                if cand != tok and (valid(cand) or freq_plain.get(cand.lower(), 0) >= args.target_freq):
                    proposals.append({"type": "confusion", "from": tok, "to": cand,
                                      "from_freq": f, "to_freq": freq_plain.get(cand.lower(), 0),
                                      "context": context(tok)})
                    done = True
                    break
            if done:
                break

    # B. broken line-break hyphen (join is frequent in the document)
    for tok in tokens:
        low = tok.lower()
        if tok.count("-") != 1 or low in seen:
            continue
        seen.add(low)
        a, b = tok.split("-")
        join = (a + b).lower()
        if len(join) < args.min_len:
            continue
        join_freq = freq_plain.get(join, 0)
        join_ok = join_freq >= 2 or valid(a + b)
        halves_words = all((valid(part) or freq_plain.get(part.lower(), 0) >= args.target_freq) for part in (a, b))
        if join_ok and not halves_words and freq_hyph[low] == 1 and b[:1].islower():
            proposals.append({"type": "dehyphen", "from": tok, "to": a + b,
                              "from_freq": 1, "to_freq": join_freq, "context": context(tok)})

    Path(args.out).write_text(json.dumps(proposals, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Proposals: {len(proposals)} (confusion + dehyphen) -> {args.out}")
    print("Review and prune before `apply` — this is high-precision, NOT complete.")


# --------------------------------------------------------------------------- apply
def single_t(r: etree._Element) -> Optional[etree._Element]:
    ts = r.findall("w:t", NS)
    return ts[0] if len(ts) == 1 else None


def set_t(node: etree._Element, value: str) -> None:
    node.text = value
    if value != value.strip():
        node.set(XML_SPACE, "preserve")
    else:
        node.attrib.pop(XML_SPACE, None)


def apply_case(matched: str, repl: str) -> str:
    if matched[:1].isupper():
        return repl[:1].upper() + repl[1:]
    return repl[:1].lower() + repl[1:]


def process_paragraph(p: etree._Element, patterns, counts: Counter, skipped: list) -> None:
    runs = p.findall(".//w:r", NS)
    spans = []
    pos = 0
    for r in runs:
        t = single_t(r)
        txt = (t.text or "") if t is not None else "".join(n.text or "" for n in r.findall("w:t", NS))
        spans.append([pos, pos + len(txt), r, t, txt])
        pos += len(txt)
    full = "".join(s[4] for s in spans)
    if not full:
        return
    matches = []
    claimed = [False] * len(full)
    for pat, frm, to in patterns:
        for m in pat.finditer(full):
            s, e = m.start(), m.end()
            if any(claimed[s:e]):
                continue
            for i in range(s, e):
                claimed[i] = True
            matches.append((s, e, m.group(0), to, frm))
    if not matches:
        return
    matches.sort(reverse=True)
    for s, e, matched, to, frm in matches:
        repl = apply_case(matched, to)
        covered = [i for i, sp in enumerate(spans) if sp[0] < e and sp[1] > s]
        if any(single_t(spans[i][2]) is None for i in covered):
            skipped.append({"from": frm, "reason": "non-simple-run"})
            continue
        if len(covered) == 1:
            i = covered[0]
            rs = spans[i][0]
            txt = spans[i][4]
            new = txt[: s - rs] + repl + txt[e - rs:]
            set_t(spans[i][3], new)
            spans[i][4] = new
            spans[i][1] = rs + len(new)
        else:
            first, last = covered[0], covered[-1]
            set_t(spans[first][3], spans[first][4][: s - spans[first][0]] + repl)
            for mid in covered[1:-1]:
                set_t(spans[mid][3], "")
            set_t(spans[last][3], spans[last][4][e - spans[last][0]:])
        counts[frm] += 1


def cmd_apply(args) -> None:
    corrections = json.loads(Path(args.map).read_text(encoding="utf-8"))
    corrections.sort(key=lambda c: len(c["from"]), reverse=True)
    patterns = [
        (re.compile(rf"(?<![{LETTER}]){re.escape(c['from'])}(?![{LETTER}])", re.IGNORECASE), c["from"], c["to"])
        for c in corrections
    ]
    counts: Counter = Counter()
    skipped: list = []
    src, out = Path(args.input), Path(args.output)
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        names = set(zin.namelist())
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename in PARTS and info.filename in names:
                root = etree.fromstring(data)
                for p in root.findall(".//w:p", NS):
                    process_paragraph(p, patterns, counts, skipped)
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone="yes")
            zout.writestr(info, data)
    applied = sum(counts.values())
    not_found = [c["from"] for c in corrections if counts.get(c["from"], 0) == 0]
    report = {
        "input": str(src), "output": str(out), "corrections_total": len(corrections),
        "applied_occurrences": applied, "applied_unique": len([k for k, v in counts.items() if v]),
        "per_correction": dict(counts), "not_found": not_found, "skipped_non_simple": skipped,
    }
    if args.report_json:
        Path(args.report_json).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Applied {applied} occurrences over {report['applied_unique']}/{len(corrections)} corrections")
    if not_found:
        print(f"NOT FOUND ({len(not_found)}): {', '.join(not_found)}")
    if skipped:
        print(f"SKIPPED non-simple runs: {len(skipped)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Corpus-internal OCR detection + reviewed-map correction for DOCX")
    sub = parser.add_subparsers(dest="cmd", required=True)
    det = sub.add_parser("detect", help="build a high-precision correction proposal JSON (non-destructive)")
    det.add_argument("input")
    det.add_argument("out", help="proposals JSON path")
    det.add_argument("--dict", default="/usr/share/hunspell/ru_RU", help="hunspell dictionary base path")
    det.add_argument("--max-freq", type=int, default=2, help="only suspect tokens with freq <= this")
    det.add_argument("--target-freq", type=int, default=4, help="correction target must be at least this frequent")
    det.add_argument("--min-len", type=int, default=4)
    ap = sub.add_parser("apply", help="apply an explicit reviewed [{from,to}] correction map")
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--map", required=True, help="reviewed corrections JSON: [{\"from\":..,\"to\":..}]")
    ap.add_argument("--report-json")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.cmd == "detect":
        cmd_detect(args)
    elif args.cmd == "apply":
        cmd_apply(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
