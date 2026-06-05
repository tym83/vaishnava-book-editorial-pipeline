#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Apply shloka paragraph styles and inline-verse italics from a reviewed plan.

The plan is an explicit, human-reviewed JSON so that the verse/translation
boundaries and the exact inline spans are never guessed at apply time:

    {
      "shloka_ranges": [[286, 304], [324, 372]],   // body-paragraph index ranges
      "body_ranges":   [[306, 321], [374, 388]],    // poem-translation ranges
      "italic_spans":  [{"para": 166, "span": "Шринатхе джанаки-натхе ..."}]
    }

- non-empty paragraphs in ``shloka_ranges`` get the ``Шлока`` paragraph style;
- non-empty paragraphs in ``body_ranges`` get the ``Основной текст`` style;
- each ``italic_spans`` entry receives the ``Char Курсив`` character style on the
  exact substring (across runs), leaving already-italic slices untouched.

Paragraph indices are 0-based over ``.//w:body/w:p`` (document.xml only), matching
how the verse detector enumerates paragraphs.  Only lxml is required.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Optional

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"w": W_NS}
W = f"{{{W_NS}}}"
XML_SPACE = f"{{{XML_NS}}}space"
SHLOKA_NAME = "Шлока"
BODY_NAME = "Основной текст"
ITALIC_NAME = "Char Курсив"


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def name_to_id(styles_root: etree._Element) -> dict:
    out = {}
    for s in styles_root.findall("w:style", NS):
        nm = s.find("w:name", NS)
        if nm is not None:
            out[nm.get(W + "val")] = s.get(W + "styleId")
    return out


def para_text(p: etree._Element) -> str:
    return "".join(n.text or "" for n in p.findall(".//w:t", NS))


def cur_style(p: etree._Element) -> Optional[str]:
    ps = p.find("w:pPr/w:pStyle", NS)
    return ps.get(W + "val") if ps is not None else None


def set_pstyle(p: etree._Element, style_id: str) -> None:
    ppr = p.find("w:pPr", NS)
    if ppr is None:
        ppr = etree.Element(W + "pPr")
        p.insert(0, ppr)
    ps = ppr.find("w:pStyle", NS)
    if ps is None:
        ps = etree.Element(W + "pStyle")
        ppr.insert(0, ps)
    ps.set(W + "val", style_id)


def single_t(r: etree._Element) -> Optional[etree._Element]:
    ts = r.findall("w:t", NS)
    return ts[0] if len(ts) == 1 else None


def set_t(node: etree._Element, value: str) -> None:
    node.text = value
    if value != value.strip():
        node.set(XML_SPACE, "preserve")
    else:
        node.attrib.pop(XML_SPACE, None)


def run_is_italic(r: etree._Element, italic_id: str) -> bool:
    rs = r.find("w:rPr/w:rStyle", NS)
    if rs is not None and rs.get(W + "val") == italic_id:
        return True
    rpr = r.find("w:rPr", NS)
    return rpr is not None and (rpr.find("w:i", NS) is not None or rpr.find("w:iCs", NS) is not None)


def clone_run(template: etree._Element, text: str, italic: bool, italic_id: str) -> etree._Element:
    nr = deepcopy(template)
    for t in nr.findall("w:t", NS):
        nr.remove(t)
    if italic:
        rpr = nr.find("w:rPr", NS)
        if rpr is None:
            rpr = etree.Element(W + "rPr")
            nr.insert(0, rpr)
        rs = rpr.find("w:rStyle", NS)
        if rs is None:
            rs = etree.Element(W + "rStyle")
            rpr.insert(0, rs)
        rs.set(W + "val", italic_id)
    nt = etree.SubElement(nr, W + "t")
    set_t(nt, text)
    return nr


def italicize_range(p: etree._Element, s: int, e: int, italic_id: str) -> bool:
    runs = p.findall(".//w:r", NS)
    spans = []
    pos = 0
    for r in runs:
        t = single_t(r)
        txt = (t.text or "") if t is not None else "".join(n.text or "" for n in r.findall("w:t", NS))
        spans.append([pos, pos + len(txt), r, txt])
        pos += len(txt)
    schedule = {}
    for i, (rs, re_, r, txt) in enumerate(spans):
        if rs >= e or re_ <= s or single_t(r) is None or run_is_italic(r, italic_id):
            continue
        ls, le = max(s, rs) - rs, min(e, re_) - rs
        if le > ls:
            schedule.setdefault(i, []).append((ls, le))
    for i, ivs in schedule.items():
        rs, re_, r, txt = spans[i]
        ivs.sort()
        merged = []
        for a, b in ivs:
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        parent = r.getparent()
        idx = parent.index(r)
        newruns = []
        cur = 0
        for a, b in merged:
            if a > cur:
                newruns.append(clone_run(r, txt[cur:a], False, italic_id))
            newruns.append(clone_run(r, txt[a:b], True, italic_id))
            cur = b
        if cur < len(txt):
            newruns.append(clone_run(r, txt[cur:], False, italic_id))
        parent.remove(r)
        for off, nr in enumerate(newruns):
            parent.insert(idx + off, nr)
    return bool(schedule)


def cmd_apply(args) -> None:
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    src, out = Path(args.input), Path(args.output)
    zin = zipfile.ZipFile(src)
    ids = name_to_id(etree.fromstring(zin.read("word/styles.xml")))
    for required in (SHLOKA_NAME, BODY_NAME, ITALIC_NAME):
        if required not in ids:
            die(f"style '{required}' not found in styles.xml")
    shloka, body, italic = ids[SHLOKA_NAME], ids[BODY_NAME], ids[ITALIC_NAME]

    root = etree.fromstring(zin.read("word/document.xml"))
    P = root.findall(".//w:body/w:p", NS)
    log = {"to_shloka": [], "to_body": [], "italic": [], "italic_notfound": []}

    for a, b in plan.get("shloka_ranges", []):
        for i in range(a, b + 1):
            if i < len(P) and para_text(P[i]).strip() and cur_style(P[i]) != shloka:
                set_pstyle(P[i], shloka)
                log["to_shloka"].append(i)
    for a, b in plan.get("body_ranges", []):
        for i in range(a, b + 1):
            if i < len(P) and para_text(P[i]).strip() and cur_style(P[i]) not in (body, None):
                set_pstyle(P[i], body)
                log["to_body"].append(i)
    for item in plan.get("italic_spans", []):
        i, span = item["para"], item["span"]
        if i >= len(P):
            log["italic_notfound"].append(item)
            continue
        pos = para_text(P[i]).find(span)
        if pos < 0:
            log["italic_notfound"].append(item)
            continue
        if italicize_range(P[i], pos, pos + len(span), italic):
            log["italic"].append({"para": i, "span": span})

    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone="yes")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            zout.writestr(info, data if info.filename == "word/document.xml" else zin.read(info.filename))

    summary = {
        "to_shloka_count": len(log["to_shloka"]), "to_shloka": log["to_shloka"],
        "to_body_count": len(log["to_body"]), "to_body": log["to_body"],
        "italic_count": len(log["italic"]), "italic": log["italic"],
        "italic_notfound": log["italic_notfound"],
    }
    if args.report_json:
        Path(args.report_json).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"-> Шлока: {summary['to_shloka_count']} paragraphs {log['to_shloka']}")
    print(f"-> Основной текст: {summary['to_body_count']} paragraphs {log['to_body']}")
    print(f"-> Char Курсив: {summary['italic_count']} spans")
    if log["italic_notfound"]:
        print(f"NOT FOUND spans: {len(log['italic_notfound'])}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply shloka paragraph styles and inline-verse italics from a plan")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ap = sub.add_parser("apply")
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--plan", required=True, help="reviewed plan JSON (shloka_ranges / body_ranges / italic_spans)")
    ap.add_argument("--report-json")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.cmd == "apply":
        cmd_apply(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
