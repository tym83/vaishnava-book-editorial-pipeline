#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Extract italic spans from gold-corpus books to seed the glossary.

The clean, post-proofreading books are an authoritative record of *what the
house style actually italicises*.  This tool reads each book, collects every
italic run/span together with its surrounding sentence, normalises it, and
emits frequency-ranked candidates for the italic glossary.

Inputs:
- ``.docx`` — italic detected from direct ``w:i``/``w:iCs`` formatting and from
  the canonical ``Char Курсив`` character style (and any style whose effective
  run properties resolve to italic, following ``basedOn``).
- ``.pdf``  — italic detected via PyMuPDF span flags / font-name heuristics.

Outputs (``--out-dir``):
- ``italic_spans.csv``      every span occurrence with source + context;
- ``italic_candidates.csv`` deduped, frequency-ranked, with ``in_glossary`` flag.

Raw context sentences come from copyrighted books — keep the per-occurrence file
in a working directory, only the short candidate terms are meant for the repo.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent))

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
W = f"{{{W_NS}}}"
DOCX_TEXT_PARTS = ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml")

# Spans longer than this (in words) are treated as running italic text — most
# likely a transliterated verse line, not a glossary term — and routed to a
# separate bucket instead of the term candidates.
MAX_TERM_WORDS = 5
SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
EDGE_PUNCT = "\"'«»“”„‘’()[]{}.,;:!?…—–-  \t\r\n"


# --------------------------------------------------------------------------- #
# DOCX
# --------------------------------------------------------------------------- #
def _basedon_italic(styles_root: etree._Element) -> Set[str]:
    """Return style ids whose effective run props resolve to italic."""
    by_id: Dict[str, etree._Element] = {}
    for st in styles_root.findall("w:style", NS):
        sid = st.get(W + "styleId")
        if sid:
            by_id[sid] = st

    def direct_italic(st: etree._Element) -> Optional[bool]:
        rpr = st.find("w:rPr", NS)
        if rpr is None:
            return None
        if rpr.find("w:i", NS) is not None or rpr.find("w:iCs", NS) is not None:
            # honour explicit w:i val="0"
            i = rpr.find("w:i", NS)
            if i is not None and i.get(W + "val") in ("0", "false"):
                return False
            return True
        return None

    italic: Set[str] = set()
    for sid, st in by_id.items():
        seen: Set[str] = set()
        cur: Optional[etree._Element] = st
        verdict: Optional[bool] = None
        while cur is not None and (cid := cur.get(W + "styleId")) not in seen:
            seen.add(cid)
            verdict = direct_italic(cur)
            if verdict is not None:
                break
            based = cur.find("w:basedOn", NS)
            cur = by_id.get(based.get(W + "val")) if based is not None else None
        # also treat the canonical italic char style by name
        name_el = st.find("w:name", NS)
        nm = name_el.get(W + "val") if name_el is not None else ""
        if verdict or (nm and "курсив" in nm.lower()):
            italic.add(sid)
    return italic


def _run_is_italic(r: etree._Element, italic_style_ids: Set[str]) -> bool:
    rstyle = r.find("w:rPr/w:rStyle", NS)
    if rstyle is not None and rstyle.get(W + "val") in italic_style_ids:
        return True
    rpr = r.find("w:rPr", NS)
    if rpr is None:
        return False
    i = rpr.find("w:i", NS)
    if i is not None and i.get(W + "val") not in ("0", "false"):
        return True
    ics = rpr.find("w:iCs", NS)
    if ics is not None and ics.get(W + "val") not in ("0", "false"):
        return True
    return False


def _run_text(r: etree._Element) -> str:
    parts: List[str] = []
    for node in r.iter():
        tag = etree.QName(node).localname
        if tag == "t":
            parts.append(node.text or "")
        elif tag in ("tab",):
            parts.append("\t")
        elif tag in ("br", "cr"):
            parts.append("\n")
    return "".join(parts)


def iter_docx_spans(path: Path) -> Iterable[Tuple[str, str]]:
    """Yield (italic_span_text, paragraph_text) for every italic span."""
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        styles_root = (
            etree.fromstring(zf.read("word/styles.xml"))
            if "word/styles.xml" in names
            else etree.fromstring(b"<root/>")
        )
        italic_style_ids = _basedon_italic(styles_root)
        for part in DOCX_TEXT_PARTS:
            if part not in names:
                continue
            root = etree.fromstring(zf.read(part))
            for p in root.iter(f"{W}p"):
                runs = p.findall(".//w:r", NS)
                if not runs:
                    continue
                para_text = "".join(_run_text(r) for r in runs)
                cur: List[str] = []
                for r in runs:
                    txt = _run_text(r)
                    if not txt:
                        continue
                    if _run_is_italic(r, italic_style_ids):
                        cur.append(txt)
                    else:
                        if cur:
                            yield "".join(cur), para_text
                            cur = []
                if cur:
                    yield "".join(cur), para_text


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #
def iter_pdf_spans(path: Path) -> Iterable[Tuple[str, str]]:
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    try:
        for page in doc:
            data = page.get_text("dict")
            for block in data.get("blocks", []):
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    line_text = "".join(s.get("text", "") for s in spans)
                    cur: List[str] = []
                    for s in spans:
                        txt = s.get("text", "")
                        if not txt:
                            continue
                        flags = s.get("flags", 0)
                        font = (s.get("font", "") or "").lower()
                        is_italic = bool(flags & 2) or "italic" in font or "oblique" in font
                        if is_italic:
                            cur.append(txt)
                        else:
                            if cur:
                                yield "".join(cur), line_text
                                cur = []
                    if cur:
                        yield "".join(cur), line_text
    finally:
        doc.close()


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #
def normalise_term(raw: str) -> str:
    s = unicodedata.normalize("NFC", raw)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(EDGE_PUNCT)
    return s.strip()


def context_sentence(span: str, para: str) -> str:
    para = re.sub(r"\s+", " ", para).strip()
    if not span or span not in para:
        return para[:200]
    for sent in SENTENCE_SPLIT.split(para):
        if span in sent:
            return sent.strip()[:300]
    return para[:300]


def is_term_like(term: str) -> bool:
    if len(term) < 2:
        return False
    if not re.search(r"[A-Za-zА-Яа-яЁё]", term):
        return False  # pure digits / punctuation
    return True


def load_glossary_forms(glossary_csv: Optional[Path]) -> Set[str]:
    forms: Set[str] = set()
    if not glossary_csv or not glossary_csv.exists():
        return forms
    with glossary_csv.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            for col in ("approved_form", "lemma_ru", "allowed_forms"):
                val = (row.get(col) or "").strip()
                for piece in re.split(r"[|;]", val):
                    piece = piece.strip().lower()
                    if piece:
                        forms.add(piece)
    return forms


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("books", nargs="+", type=Path, help=".docx / .pdf gold books")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--glossary", type=Path, default=None,
                    help="glossary_approved.csv to flag already-known forms")
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    known = load_glossary_forms(args.glossary)

    occ_rows: List[Dict[str, str]] = []
    # key -> aggregate
    agg: Dict[str, Dict] = defaultdict(
        lambda: {"surface": "", "total": 0, "sources": defaultdict(int),
                 "contexts": [], "is_phrase": False}
    )

    for book in args.books:
        if not book.exists():
            print(f"WARN: missing {book}", file=sys.stderr)
            continue
        suffix = book.suffix.lower()
        if suffix == ".docx":
            spans = iter_docx_spans(book)
        elif suffix == ".pdf":
            spans = iter_pdf_spans(book)
        else:
            print(f"WARN: unsupported {book}", file=sys.stderr)
            continue

        src = book.name
        n = 0
        for raw_span, para in spans:
            term = normalise_term(raw_span)
            if not is_term_like(term):
                continue
            n += 1
            ctx = context_sentence(term, para)
            occ_rows.append({"source": src, "term": term, "context": ctx})
            key = term.lower()
            a = agg[key]
            if not a["surface"]:
                a["surface"] = term
            a["total"] += 1
            a["sources"][src] += 1
            if len(a["contexts"]) < 3:
                a["contexts"].append(f"[{src}] {ctx}")
            if len(term.split()) > MAX_TERM_WORDS:
                a["is_phrase"] = True
        print(f"{src}: {n} italic spans", file=sys.stderr)

    # write per-occurrence file
    occ_path = args.out_dir / "italic_spans.csv"
    with occ_path.open("w", encoding="utf-8", newline="") as fh:
        wtr = csv.DictWriter(fh, fieldnames=["source", "term", "context"])
        wtr.writeheader()
        wtr.writerows(occ_rows)

    # write aggregated candidates
    cand_path = args.out_dir / "italic_candidates.csv"
    rows = sorted(agg.items(), key=lambda kv: (-kv[1]["total"], kv[0]))
    with cand_path.open("w", encoding="utf-8", newline="") as fh:
        wtr = csv.writer(fh)
        wtr.writerow(["term", "total", "by_source", "is_long_phrase",
                      "in_glossary", "sample_contexts"])
        for key, a in rows:
            by_src = "; ".join(f"{s}:{c}" for s, c in sorted(a["sources"].items()))
            wtr.writerow([
                a["surface"], a["total"], by_src,
                "yes" if a["is_phrase"] else "",
                "yes" if key in known else "",
                " || ".join(a["contexts"]),
            ])

    print(f"\nwrote {occ_path} ({len(occ_rows)} occurrences)")
    print(f"wrote {cand_path} ({len(rows)} distinct candidates)")


if __name__ == "__main__":
    main()
