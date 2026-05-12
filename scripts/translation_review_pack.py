#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Create side-by-side EN/RU markdown packs for translation review.

This generic packer is intentionally conservative: it does not claim precise
paragraph alignment.  It splits source text and target DOCX by cumulative word
progress into the same number of reviewable chunks, preserving paragraph
indices, style names, and digit signatures for human/LLM comparison.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from docx import Document


DIACRITIC_RE = re.compile(r"[ĀāĪīŪūṚṛṜṝḶḷṂṃṄṅÑñṆṇṬṭḌḍḤḥŚśṢṣ]")


@dataclass(frozen=True)
class Block:
    index: int
    kind: str
    text: str
    words: int
    digits: str


@dataclass(frozen=True)
class PackSummary:
    code: str
    output: str
    source_blocks: int
    target_blocks: int
    source_words: int
    target_words: int


def clean_text(text: str) -> str:
    return " ".join((text or "").replace("\u00a0", " ").split())


def word_count(text: str) -> int:
    return len(re.findall(r"[\wĀāĪīŪūṚṛṜṝḶḷṂṃṄṅÑñṆṇṬṭḌḍḤḥŚśṢṣ'-]+", text, re.UNICODE))


def digit_signature(text: str) -> str:
    return "|".join(re.findall(r"\d+(?:\.\d+)*(?:[–-]\d+(?:\.\d+)*)?", text)[:16])


def classify_source_block(text: str) -> str:
    words = word_count(text)
    if words <= 12 and not text.endswith((".", "!", "?", ":", ";", ",")):
        return "heading_like"
    if DIACRITIC_RE.search(text) and words <= 50:
        return "sanskrit_or_term"
    if re.fullmatch(r"[\divxlcdmIVXLCDM .–-]+", text):
        return "page_or_number"
    return "body"


def read_source_blocks(path: Path) -> List[Block]:
    text = path.read_text(encoding="utf-8", errors="replace")
    raw_blocks = re.split(r"\n\s*\n", text.replace("\f", "\n\n"))
    blocks: List[Block] = []
    for raw in raw_blocks:
        cleaned = clean_text(raw)
        if not cleaned:
            continue
        if len(cleaned) <= 3 and re.fullmatch(r"[\divxlcdmIVXLCDM]+", cleaned):
            continue
        blocks.append(
            Block(
                index=len(blocks) + 1,
                kind=classify_source_block(cleaned),
                text=cleaned,
                words=word_count(cleaned),
                digits=digit_signature(cleaned),
            )
        )
    return blocks


def read_target_blocks(path: Path) -> List[Block]:
    doc = Document(str(path))
    blocks: List[Block] = []
    for para_index, para in enumerate(doc.paragraphs, start=1):
        cleaned = clean_text(para.text)
        if not cleaned:
            continue
        style = para.style.name if para.style is not None else ""
        blocks.append(
            Block(
                index=para_index,
                kind=style,
                text=cleaned,
                words=word_count(cleaned),
                digits=digit_signature(cleaned),
            )
        )
    return blocks


def split_evenly(blocks: Sequence[Block], chunk_count: int) -> List[List[Block]]:
    if chunk_count <= 1:
        return [list(blocks)]
    total_words = max(1, sum(block.words for block in blocks))
    chunks: List[List[Block]] = []
    current: List[Block] = []
    current_words = 0
    next_cut = total_words / chunk_count
    produced = 0
    for block in blocks:
        current.append(block)
        current_words += block.words
        if produced < chunk_count - 1 and current_words >= next_cut * (produced + 1):
            chunks.append(current)
            current = []
            produced += 1
    chunks.append(current)
    while len(chunks) < chunk_count:
        chunks.append([])
    return chunks[:chunk_count]


def issue_excerpt(text: str, limit: int = 220) -> str:
    text = clean_text(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def load_issues_by_paragraph(path: Path | None) -> Dict[int, List[dict]]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    issues_by_paragraph: Dict[int, List[dict]] = {}
    for issue in data.get("issues", []):
        anchor = issue.get("anchor") or {}
        if anchor.get("part") != "word/document.xml":
            continue
        paragraph_index = anchor.get("paragraph_index")
        if not isinstance(paragraph_index, int):
            continue
        issues_by_paragraph.setdefault(paragraph_index, []).append(issue)
    return issues_by_paragraph


def block_lines(prefix: str, blocks: Iterable[Block], issues_by_paragraph: Dict[int, List[dict]] | None = None) -> List[str]:
    lines: List[str] = []
    issues_by_paragraph = issues_by_paragraph or {}
    for block in blocks:
        digits = f"; digits={block.digits}" if block.digits else ""
        lines.append(f"### {prefix} {block.index:04d} [{block.kind}; words={block.words}{digits}]")
        lines.append(block.text)
        issues = issues_by_paragraph.get(block.index, [])
        if issues:
            lines.append("")
            lines.append("Existing Word comments for this paragraph:")
            for issue in issues:
                title = clean_text(issue.get("title", ""))
                kind = clean_text(issue.get("kind", ""))
                message = issue_excerpt(issue.get("message", ""))
                suggestion = issue_excerpt(issue.get("suggestion", ""))
                lines.append(f"- `{issue.get('id', '')}` [{issue.get('severity', 'warning')}/{kind}] {title}")
                if message:
                    lines.append(f"  Message: {message}")
                if suggestion:
                    lines.append(f"  Suggested action: {suggestion}")
        lines.append("")
    return lines


def write_pack(
    code: str,
    source_blocks: Sequence[Block],
    target_blocks: Sequence[Block],
    out_path: Path,
    source_path: Path,
    target_path: Path,
    target_issues: Dict[int, List[dict]],
) -> PackSummary:
    lines = [
        f"# Translation Review Pack {code}",
        "",
        f"- Source: `{source_path}`",
        f"- Target: `{target_path}`",
        f"- Source blocks: {len(source_blocks)}",
        f"- Target blocks: {len(target_blocks)}",
        f"- Source words: {sum(block.words for block in source_blocks)}",
        f"- Target words: {sum(block.words for block in target_blocks)}",
        "",
        "## Source Blocks",
        "",
    ]
    lines.extend(block_lines("SRC", source_blocks))
    lines.append("## Target Blocks")
    lines.append("")
    lines.extend(block_lines("RU", target_blocks, target_issues))
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return PackSummary(
        code=code,
        output=str(out_path),
        source_blocks=len(source_blocks),
        target_blocks=len(target_blocks),
        source_words=sum(block.words for block in source_blocks),
        target_words=sum(block.words for block in target_blocks),
    )


def build_packs(
    source_path: Path,
    target_path: Path,
    output_dir: Path,
    *,
    chunk_words: int,
    min_chunks: int,
    issues_json: Path | None,
) -> List[PackSummary]:
    source_blocks = read_source_blocks(source_path)
    target_blocks = read_target_blocks(target_path)
    target_issues = load_issues_by_paragraph(issues_json)
    total_words = max(sum(block.words for block in source_blocks), sum(block.words for block in target_blocks))
    chunk_count = max(min_chunks, int(math.ceil(total_words / max(1, chunk_words))))
    output_dir.mkdir(parents=True, exist_ok=True)
    source_chunks = split_evenly(source_blocks, chunk_count)
    target_chunks = split_evenly(target_blocks, chunk_count)
    packs = [
        write_pack(
            f"{index:03d}",
            source_chunks[index - 1],
            target_chunks[index - 1],
            output_dir / f"{index:03d}.md",
            source_path,
            target_path,
            target_issues,
        )
        for index in range(1, chunk_count + 1)
    ]
    index_json = {
        "version": 1,
        "report_kind": "translation_review_pack_index",
        "source": str(source_path),
        "target": str(target_path),
        "chunk_words": chunk_words,
        "issues_json": str(issues_json) if issues_json else "",
        "chunks": [asdict(pack) for pack in packs],
    }
    (output_dir / "index.json").write_text(json.dumps(index_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Translation Review Pack Index",
        "",
        f"- Source: `{source_path}`",
        f"- Target: `{target_path}`",
        f"- Existing comments: `{issues_json}`" if issues_json else "- Existing comments: `<none>`",
        f"- Chunk words: {chunk_words}",
        f"- Packs: {len(packs)}",
        "",
        "| Code | Source blocks | Target blocks | Source words | Target words |",
        "|---|---:|---:|---:|---:|",
    ]
    for pack in packs:
        lines.append(
            f"| {pack.code} | {pack.source_blocks} | {pack.target_blocks} | {pack.source_words} | {pack.target_words} |"
        )
    (output_dir / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return packs


def main() -> int:
    parser = argparse.ArgumentParser(description="Create side-by-side source/target translation review packs")
    parser.add_argument("source_text")
    parser.add_argument("target_docx")
    parser.add_argument("output_dir")
    parser.add_argument("--chunk-words", type=int, default=1800)
    parser.add_argument("--min-chunks", type=int, default=1)
    parser.add_argument("--issues-json", help="Optional issue bundle to show existing Word comments by target paragraph")
    args = parser.parse_args()
    packs = build_packs(
        Path(args.source_text),
        Path(args.target_docx),
        Path(args.output_dir),
        chunk_words=args.chunk_words,
        min_chunks=args.min_chunks,
        issues_json=Path(args.issues_json) if args.issues_json else None,
    )
    print(f"Wrote {len(packs)} packs to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
