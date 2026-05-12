#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""
Structural EN/RU comparator for chapter-level translation completeness review.

v1 goals:
- compare source and translation without pretending to do semantic bilingual review
- find suspicious structural mismatches:
  * missing / extra blocks
  * heading/list/shloka/source/caption mismatches
  * footnote reference count mismatches
  * suspicious numeric/reference anchor mismatches
- work on chapter pairs or chapter directories

Examples:
  python3 source_ru_comparator.py compare en.docx ru.docx --report-md out.md --report-json out.json
  python3 source_ru_comparator.py compare-dir en_dir ru_dir out_dir
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
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from lxml import etree

from vedabase_reference_resolver import scan_input_for_references


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
W = f"{{{W_NS}}}"

SCRIPTURE_REF_PATTERN = re.compile(
    r"(?i)\b("
    r"шб|бг|чч|ав|гв|сдж|шбут|шпу|SB|Bg|Cc|"
    r"adi|madhya|antya|"
    r"патр|патрāвалӣ|gaudiya"
    r")\b"
)
COMBINING_MARKS = "\u0304\u0323\u0307\u0303\u0301"


@dataclass
class Block:
    index: int
    part: str
    text: str
    style_name: Optional[str]
    kind: str
    word_count: int
    char_count: int
    footnote_refs: int
    digit_signature: str
    has_quote_marks: bool
    translit_score: int


@dataclass
class StructureIssue:
    kind: str
    source_range: Tuple[int, int]
    target_range: Tuple[int, int]
    source_excerpt: str
    target_excerpt: str
    details: Dict[str, object]


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def clean_text(text: str) -> str:
    return " ".join((text or "").replace("\u00a0", " ").strip().split())


def excerpt(text: str, limit: int = 180) -> str:
    text = clean_text(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def convert_doc_to_docx(path: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="source-ru-comparator-doc-"))
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


def convert_pdf_to_text(path: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="source-ru-comparator-pdf-"))
    out = temp_dir / f"{path.stem}.txt"
    subprocess.run(
        ["pdftotext", "-layout", str(path), str(out)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if not out.exists():
        die(f"Could not extract text from {path}")
    return out


def resolve_source(path: Path) -> tuple[Path, str, Optional[Path]]:
    if not path.exists():
        die(f"Input not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".json":
        return path, "normalized_json", None
    if suffix == ".doc":
        converted = convert_doc_to_docx(path)
        return converted, "docx", converted.parent
    if suffix == ".docx":
        return path, "docx", None
    if suffix == ".pdf":
        extracted = convert_pdf_to_text(path)
        return extracted, "txt", extracted.parent
    if suffix in {".txt", ".md"}:
        return path, "txt", None
    die(f"Unsupported input format: {path.suffix}")


def cleanup_temp(temp_dir: Optional[Path]) -> None:
    if temp_dir and temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)


class StyleCatalog:
    def __init__(self, root):
        self.by_id: Dict[str, str] = {}
        self.default_by_type: Dict[str, str] = {}
        for style in root.xpath(".//w:style", namespaces=NS):
            style_id = style.get(f"{W}styleId")
            name_node = style.find("w:name", namespaces=NS)
            name = name_node.get(f"{W}val") if name_node is not None else style_id
            if style_id and name:
                self.by_id[style_id] = name
            style_type = style.get(f"{W}type") or "unknown"
            if style.get(f"{W}default") in {"1", "true", "True"} and style_type not in self.default_by_type:
                self.default_by_type[style_type] = name

    def style_name(self, style_id: Optional[str]) -> Optional[str]:
        if not style_id:
            return None
        return self.by_id.get(style_id, style_id)

    def default_style_name(self, style_type: str) -> Optional[str]:
        return self.default_by_type.get(style_type)


def visible_text(node) -> str:
    return "".join(t.text or "" for t in node.xpath(".//w:t", namespaces=NS)).strip()


def count_footnote_refs(node) -> int:
    return len(node.xpath(".//w:footnoteReference", namespaces=NS))


def translit_score(text: str) -> int:
    score = 0
    score += sum(text.count(ch) for ch in COMBINING_MARKS)
    score += len(re.findall(r"[A-Za-zĀāĪīŪūṚṛṜṝḶḷṂṃṄṅÑñṆṇṬṭḌḍḤḥŚśṢṣ]", text))
    score += len(re.findall(r"[А-Яа-яЁё][̣̄̇̃́]", text))
    return score


def looks_like_transliteration_text(text: str) -> bool:
    t = clean_text(text)
    if not t:
        return False
    words = t.split()
    if len(words) > 40 or re.search(r"[.!?]", t):
        return False
    if any(mark in t for mark in COMBINING_MARKS):
        return True
    if re.search(r"[A-Za-zĀāĪīŪūṚṛṜṝḶḷṂṃṄṅÑñṆṇṬṭḌḍḤḥŚśṢṣ]", t):
        latin_words = re.findall(r"\b[A-Za-zĀāĪīŪūṚṛṜṝḶḷṂṃṄṅÑñṆṇṬṭḌḍḤḥŚśṢṣ][A-Za-zĀāĪīŪūṚṛṜṝḶḷṂṃṄṅÑñṆṇṬṭḌḍḤḥŚśṢṣ-]{1,}\b", t)
        return len(latin_words) >= 3
    return False


def digit_signature(text: str) -> str:
    nums = re.findall(r"\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?", text)
    return "|".join(nums[:8])


def infer_kind(style_name: Optional[str], text: str) -> str:
    style = (style_name or "").casefold()
    t = clean_text(text)
    if not t:
        return "empty"
    if "заголовок 1" in style or style == "heading 1":
        return "heading1"
    if "заголовок 2" in style or style == "heading 2":
        return "heading2"
    if "заголовок 3" in style or style == "heading 3":
        return "heading3"
    if "заголовок 4" in style or style == "heading 4":
        return "heading4"
    if "шлока в цитате" in style:
        return "quoted_shloka"
    if "шлока" in style and "перевод" not in style:
        return "shloka"
    if "перевод шлоки" in style:
        return "shloka_translation"
    if "цитата 1" in style:
        return "quote1"
    if "цитата 2" in style:
        return "quote2"
    if "письмо" in style:
        return "letter"
    if "источник" in style:
        return "source"
    if "подпись к иллюстрации" in style:
        return "caption"
    if "список нумерованный" in style:
        return "list_numbered"
    if "список ненумерованный" in style:
        return "list_bulleted"
    if "сноска" in style or style in {"footnote text", "footnotetext"}:
        return "footnote"

    # fallback heuristics for text-only sources
    words = t.split()
    if len(words) <= 12 and not t.endswith((".", "!", "?", ":", ";", ",")):
        return "heading_like"
    if re.match(r"^\d+[\.\)]\s+", t):
        return "list_numbered"
    if re.match(r"^[\-–—*]\s+", t):
        return "list_bulleted"
    if t.startswith(("«", "\"")) and t.endswith(("»", "\"")) and len(words) <= 120:
        return "quote_like"
    if SCRIPTURE_REF_PATTERN.search(t) and re.search(r"\d", t):
        return "source_like"
    if looks_like_transliteration_text(t):
        return "shloka_like"
    return "body"


def block_signature(block: Block) -> str:
    length_bucket = "s"
    if block.word_count >= 80:
        length_bucket = "l"
    elif block.word_count >= 25:
        length_bucket = "m"
    foot_bucket = str(min(block.footnote_refs, 3))
    digit_bucket = "d" if block.digit_signature else "n"
    translit_bucket = "t" if block.translit_score >= 3 else "p"
    return f"{block.kind}:{length_bucket}:{foot_bucket}:{digit_bucket}:{translit_bucket}"


def extract_docx_blocks(path: Path) -> List[Block]:
    blocks: List[Block] = []
    with zipfile.ZipFile(path, "r") as z:
        styles_root = etree.fromstring(z.read("word/styles.xml"))
        catalog = StyleCatalog(styles_root)
        default_style = catalog.default_style_name("paragraph")
        root = etree.fromstring(z.read("word/document.xml"))
        for idx, p in enumerate(root.xpath(".//w:body/w:p", namespaces=NS), 1):
            text = visible_text(p)
            if not clean_text(text):
                continue
            p_style = p.find("w:pPr/w:pStyle", namespaces=NS)
            style_name = catalog.style_name(p_style.get(f"{W}val")) if p_style is not None else default_style
            kind = infer_kind(style_name, text)
            blocks.append(
                Block(
                    index=idx,
                    part="body",
                    text=text,
                    style_name=style_name,
                    kind=kind,
                    word_count=len(clean_text(text).split()),
                    char_count=len(clean_text(text)),
                    footnote_refs=count_footnote_refs(p),
                    digit_signature=digit_signature(text),
                    has_quote_marks=("«" in text or "»" in text or '"' in text),
                    translit_score=translit_score(text),
                )
            )
    return blocks


def extract_text_blocks(path: Path) -> List[Block]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    raw_blocks = [clean_text(x) for x in re.split(r"\n\s*\n+", text)]
    blocks: List[Block] = []
    idx = 0
    for raw in raw_blocks:
        if not raw:
            continue
        idx += 1
        kind = infer_kind(None, raw)
        blocks.append(
            Block(
                index=idx,
                part="text",
                text=raw,
                style_name=None,
                kind=kind,
                word_count=len(raw.split()),
                char_count=len(raw),
                footnote_refs=0,
                digit_signature=digit_signature(raw),
                has_quote_marks=("«" in raw or "»" in raw or '"' in raw),
                translit_score=translit_score(raw),
            )
        )
    return blocks


def extract_normalized_json_blocks(path: Path) -> List[Block]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("blocks"), list):
        die(f"Unsupported normalized JSON schema: {path}")

    blocks: List[Block] = []
    for raw in payload["blocks"]:
        if not isinstance(raw, dict):
            continue
        text = clean_text(str(raw.get("text", "")))
        if not text:
            continue
        blocks.append(
            Block(
                index=int(raw.get("index") or len(blocks) + 1),
                part=str(raw.get("part") or "normalized_json"),
                text=text,
                style_name=raw.get("style_name"),
                kind=str(raw.get("kind") or infer_kind(raw.get("style_name"), text)),
                word_count=int(raw.get("word_count") or len(text.split())),
                char_count=int(raw.get("char_count") or len(text)),
                footnote_refs=int(raw.get("footnote_refs") or 0),
                digit_signature=str(raw.get("digit_signature") or digit_signature(text)),
                has_quote_marks=bool(raw.get("has_quote_marks")) or ("«" in text or "»" in text or '"' in text),
                translit_score=int(raw.get("translit_score") or translit_score(text)),
            )
        )
    return blocks


def extract_blocks(path: Path, fmt: str) -> List[Block]:
    if fmt == "docx":
        return extract_docx_blocks(path)
    if fmt == "txt":
        return extract_text_blocks(path)
    if fmt == "normalized_json":
        return extract_normalized_json_blocks(path)
    die(f"Unsupported extraction format: {fmt}")


def compare_blocks(source_blocks: Sequence[Block], target_blocks: Sequence[Block]) -> Dict[str, object]:
    source_seq = [block_signature(x) for x in source_blocks]
    target_seq = [block_signature(x) for x in target_blocks]
    matcher = SequenceMatcher(a=source_seq, b=target_seq, autojunk=False)

    issues: List[StructureIssue] = []
    aligned_checks: List[Dict[str, object]] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for s_block, t_block in zip(source_blocks[i1:i2], target_blocks[j1:j2]):
                details = {}
                suspicious = False
                if s_block.kind != t_block.kind:
                    suspicious = True
                    details["kind_mismatch"] = [s_block.kind, t_block.kind]
                if s_block.footnote_refs != t_block.footnote_refs:
                    suspicious = True
                    details["footnote_refs"] = [s_block.footnote_refs, t_block.footnote_refs]
                if s_block.digit_signature and t_block.digit_signature and s_block.digit_signature != t_block.digit_signature:
                    suspicious = True
                    details["digit_signature"] = [s_block.digit_signature, t_block.digit_signature]
                if suspicious:
                    aligned_checks.append(
                        {
                            "source_index": s_block.index,
                            "target_index": t_block.index,
                            "source_kind": s_block.kind,
                            "target_kind": t_block.kind,
                            "source_excerpt": excerpt(s_block.text),
                            "target_excerpt": excerpt(t_block.text),
                            "details": details,
                        }
                    )
            continue

        source_excerpt = " | ".join(excerpt(x.text, 80) for x in source_blocks[i1:i2][:3])
        target_excerpt = " | ".join(excerpt(x.text, 80) for x in target_blocks[j1:j2][:3])
        issues.append(
            StructureIssue(
                kind=f"struct_{tag}",
                source_range=(i1 + 1, i2),
                target_range=(j1 + 1, j2),
                source_excerpt=source_excerpt,
                target_excerpt=target_excerpt,
                details={
                    "source_kinds": [x.kind for x in source_blocks[i1:i2][:8]],
                    "target_kinds": [x.kind for x in target_blocks[j1:j2][:8]],
                    "source_count": i2 - i1,
                    "target_count": j2 - j1,
                },
            )
        )

    source_kind_counts = Counter(x.kind for x in source_blocks)
    target_kind_counts = Counter(x.kind for x in target_blocks)

    return {
        "source_blocks": len(source_blocks),
        "target_blocks": len(target_blocks),
        "source_kind_counts": dict(source_kind_counts),
        "target_kind_counts": dict(target_kind_counts),
        "source_footnote_refs_total": sum(x.footnote_refs for x in source_blocks),
        "target_footnote_refs_total": sum(x.footnote_refs for x in target_blocks),
        "issues": [asdict(x) for x in issues],
        "aligned_suspicious": aligned_checks,
        "match_ratio": matcher.ratio(),
    }


def write_report_md(path: Path, summary: Dict[str, object]) -> None:
    lines: List[str] = []
    lines.append("# Source/RU Comparator\n\n")
    lines.append(f"Source: `{summary['source_path']}`\n\n")
    lines.append(f"Target: `{summary['target_path']}`\n\n")
    lines.append("## Summary\n\n")
    lines.append(f"- source blocks: {summary['source_blocks']}\n")
    lines.append(f"- target blocks: {summary['target_blocks']}\n")
    lines.append(f"- match ratio: {summary['match_ratio']:.4f}\n")
    lines.append(f"- source footnote refs: {summary['source_footnote_refs_total']}\n")
    lines.append(f"- target footnote refs: {summary['target_footnote_refs_total']}\n")
    lines.append("\n## Source kind counts\n\n")
    for k, v in sorted(summary["source_kind_counts"].items()):
        lines.append(f"- `{k}`: {v}\n")
    lines.append("\n## Target kind counts\n\n")
    for k, v in sorted(summary["target_kind_counts"].items()):
        lines.append(f"- `{k}`: {v}\n")
    lines.append("\n## Structural issues\n\n")
    issues = summary["issues"]
    lines.append(f"- count: {len(issues)}\n")
    for item in issues[:200]:
        lines.append(
            f"- `{item['kind']}` source {tuple(item['source_range'])} target {tuple(item['target_range'])}\n"
            f"  - source: `{item['source_excerpt']}`\n"
            f"  - target: `{item['target_excerpt']}`\n"
        )
    hidden = len(issues) - min(200, len(issues))
    if hidden > 0:
        lines.append(f"- ... {hidden} more structural issues omitted\n")
    lines.append("\n## Suspicious aligned blocks\n\n")
    suspicious = summary["aligned_suspicious"]
    lines.append(f"- count: {len(suspicious)}\n")
    for item in suspicious[:200]:
        lines.append(
            f"- source #{item['source_index']} -> target #{item['target_index']} "
            f"`{item['source_kind']}` / `{item['target_kind']}` {item['details']}\n"
            f"  - source: `{item['source_excerpt']}`\n"
            f"  - target: `{item['target_excerpt']}`\n"
        )
    hidden = len(suspicious) - min(200, len(suspicious))
    if hidden > 0:
        lines.append(f"- ... {hidden} more aligned issues omitted\n")
    reference_scan = summary.get("target_reference_scan")
    if isinstance(reference_scan, dict):
        lines.append("\n## Target Scripture References\n\n")
        lines.append(f"- references: {reference_scan.get('reference_count', 0)}\n")
        lines.append(f"- resolved: {reference_scan.get('resolved_count', 0)}\n")
        lines.append(f"- unresolved: {reference_scan.get('unresolved_count', 0)}\n")
        unresolved = [item for item in reference_scan.get("references", []) if not item.get("resolved")]
        if unresolved:
            lines.append("\n### Unresolved\n\n")
            for item in unresolved[:100]:
                lines.append(
                    f"- `{item['normalized_ref']}` block #{item['block_index']} `{item['block_locator']}`\n"
                    f"  - excerpt: `{item['block_excerpt']}`\n"
                    f"  - expected: `{item['web_path']}`\n"
                )
            hidden = len(unresolved) - min(100, len(unresolved))
            if hidden > 0:
                lines.append(f"- ... {hidden} more unresolved references omitted\n")
    path.write_text("".join(lines), encoding="utf-8")


def compare_pair(
    source_input: Path,
    target_input: Path,
    report_md: Optional[Path],
    report_json: Optional[Path],
    *,
    reference_root: Optional[Path] = None,
    reference_locale: str = "ru",
) -> Dict[str, object]:
    source_path, source_fmt, source_tmp = resolve_source(source_input)
    target_path, target_fmt, target_tmp = resolve_source(target_input)
    try:
        source_blocks = extract_blocks(source_path, source_fmt)
        target_blocks = extract_blocks(target_path, target_fmt)
        summary = compare_blocks(source_blocks, target_blocks)
        summary["source_path"] = str(source_input)
        summary["target_path"] = str(target_input)
        if reference_root is not None:
            summary["target_reference_scan"] = scan_input_for_references(
                target_input,
                vedabase_root=reference_root,
                locale=reference_locale,
                include_sections=False,
            )
        if report_json:
            report_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        if report_md:
            write_report_md(report_md, summary)
        return summary
    finally:
        cleanup_temp(source_tmp)
        cleanup_temp(target_tmp)


def numbered_stem(path: Path) -> str:
    m = re.match(r"^(\d{3})", path.stem)
    return m.group(1) if m else path.stem


def list_candidate_files(path: Path) -> List[Path]:
    out = []
    for p in sorted(path.iterdir()):
        if p.is_file() and p.suffix.lower() in {".doc", ".docx", ".pdf", ".txt", ".md", ".json"}:
            out.append(p)
    return out


def compare_dirs(
    source_dir: Path,
    target_dir: Path,
    out_dir: Path,
    *,
    reference_root: Optional[Path] = None,
    reference_locale: str = "ru",
) -> Dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)
    source_files = {numbered_stem(p): p for p in list_candidate_files(source_dir) if re.match(r"^\d{3}", p.stem)}
    target_files = {numbered_stem(p): p for p in list_candidate_files(target_dir) if re.match(r"^\d{3}", p.stem)}
    common = sorted(set(source_files) & set(target_files))
    source_only = sorted(set(source_files) - set(target_files))
    target_only = sorted(set(target_files) - set(source_files))

    chapter_reports = []
    for key in common:
        md = out_dir / f"{key}.md"
        js = out_dir / f"{key}.json"
        summary = compare_pair(
            source_files[key],
            target_files[key],
            md,
            js,
            reference_root=reference_root,
            reference_locale=reference_locale,
        )
        chapter_reports.append(
            {
                "chapter": key,
                "source": str(source_files[key]),
                "target": str(target_files[key]),
                "match_ratio": summary["match_ratio"],
                "issue_count": len(summary["issues"]),
                "aligned_suspicious_count": len(summary["aligned_suspicious"]),
                "source_blocks": summary["source_blocks"],
                "target_blocks": summary["target_blocks"],
                "target_reference_count": int(summary.get("target_reference_scan", {}).get("reference_count", 0)),
                "target_unresolved_reference_count": int(summary.get("target_reference_scan", {}).get("unresolved_count", 0)),
            }
        )

    index = {
        "source_dir": str(source_dir),
        "target_dir": str(target_dir),
        "chapters_compared": chapter_reports,
        "source_only": source_only,
        "target_only": target_only,
    }
    (out_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# Directory Compare Index\n\n"]
    lines.append(f"Source dir: `{source_dir}`\n\n")
    lines.append(f"Target dir: `{target_dir}`\n\n")
    lines.append(f"- compared: {len(chapter_reports)}\n")
    lines.append(f"- source only: {len(source_only)}\n")
    lines.append(f"- target only: {len(target_only)}\n")
    if source_only:
        lines.append(f"- source only keys: {', '.join(source_only)}\n")
    if target_only:
        lines.append(f"- target only keys: {', '.join(target_only)}\n")
    lines.append("\n## Chapters\n\n")
    for item in chapter_reports:
        lines.append(
            f"- `{item['chapter']}` ratio={item['match_ratio']:.4f} "
            f"issues={item['issue_count']} aligned={item['aligned_suspicious_count']} "
            f"blocks {item['source_blocks']}->{item['target_blocks']} "
            f"refs={item['target_reference_count']} unresolved_refs={item['target_unresolved_reference_count']}\n"
        )
    (out_dir / "index.md").write_text("".join(lines), encoding="utf-8")
    return index


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Structural comparator for source vs RU translation")
    sub = parser.add_subparsers(dest="command", required=True)

    p_cmp = sub.add_parser("compare", help="compare one source file and one target file")
    p_cmp.add_argument("source")
    p_cmp.add_argument("target")
    p_cmp.add_argument("--report-md")
    p_cmp.add_argument("--report-json")
    p_cmp.add_argument("--reference-root", help="local Vedabase root for optional scripture reference spot-checks")
    p_cmp.add_argument("--reference-locale", default="ru", help="Vedabase locale to use for reference resolution")

    p_dir = sub.add_parser("compare-dir", help="compare chapter directories by 3-digit prefix")
    p_dir.add_argument("source_dir")
    p_dir.add_argument("target_dir")
    p_dir.add_argument("output_dir")
    p_dir.add_argument("--reference-root", help="local Vedabase root for optional scripture reference spot-checks")
    p_dir.add_argument("--reference-locale", default="ru", help="Vedabase locale to use for reference resolution")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "compare":
        summary = compare_pair(
            Path(args.source),
            Path(args.target),
            Path(args.report_md) if args.report_md else None,
            Path(args.report_json) if args.report_json else None,
            reference_root=Path(args.reference_root) if args.reference_root else None,
            reference_locale=args.reference_locale,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if args.command == "compare-dir":
        summary = compare_dirs(
            Path(args.source_dir),
            Path(args.target_dir),
            Path(args.output_dir),
            reference_root=Path(args.reference_root) if args.reference_root else None,
            reference_locale=args.reference_locale,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
