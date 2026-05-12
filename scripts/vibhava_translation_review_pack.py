#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Create side-by-side EN/RU markdown packs for Vibhava translation review."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

from docx import Document


@dataclass
class Block:
    index: int
    kind: str
    text: str
    words: int
    digits: str


@dataclass
class SectionPack:
    code: str
    en_path: str
    ru_path: str
    output: str
    en_blocks: int
    ru_blocks: int
    en_words: int
    ru_words: int


def clean_text(text: str) -> str:
    return " ".join((text or "").replace("\u00a0", " ").split())


def digit_signature(text: str) -> str:
    return "|".join(re.findall(r"\d+(?:\.\d+)*(?:[–-]\d+(?:\.\d+)*)?", text)[:12])


def split_en_blocks(path: Path) -> List[Block]:
    text = path.read_text(encoding="utf-8", errors="replace")
    raw_blocks = re.split(r"\n\s*\n", text)
    blocks: List[Block] = []
    for raw in raw_blocks:
        cleaned = clean_text(raw)
        if not cleaned:
            continue
        kind = "body"
        if len(cleaned.split()) <= 12 and not cleaned.endswith((".", "!", "?", ":", ";", ",")):
            kind = "heading"
        elif re.search(r"[ĀāĪīŪūṚṛṜṝḶḷṂṃṄṅÑñṆṇṬṭḌḍḤḥŚśṢṣ]", cleaned) and len(cleaned.split()) <= 45:
            kind = "sanskrit"
        blocks.append(Block(len(blocks) + 1, kind, cleaned, len(cleaned.split()), digit_signature(cleaned)))
    return blocks


def split_ru_blocks(path: Path) -> List[Block]:
    doc = Document(str(path))
    blocks: List[Block] = []
    for para in doc.paragraphs:
        cleaned = clean_text(para.text)
        if not cleaned:
            continue
        style = para.style.name if para.style is not None else ""
        blocks.append(Block(len(blocks) + 1, style, cleaned, len(cleaned.split()), digit_signature(cleaned)))
    return blocks


def wanted_codes(en_dir: Path, explicit: Sequence[str]) -> List[str]:
    if explicit:
        return [code.zfill(3) for code in explicit]
    return [p.stem[:3] for p in sorted(en_dir.glob("[0-9][0-9][0-9].txt"))]


def write_section_pack(code: str, en_path: Path, ru_path: Path, out_path: Path) -> SectionPack:
    en_blocks = split_en_blocks(en_path)
    ru_blocks = split_ru_blocks(ru_path)
    lines = [
        f"# Translation Review Pack {code}",
        "",
        f"- EN: `{en_path}`",
        f"- RU: `{ru_path}`",
        f"- blocks: EN {len(en_blocks)} / RU {len(ru_blocks)}",
        f"- words: EN {sum(b.words for b in en_blocks)} / RU {sum(b.words for b in ru_blocks)}",
        "",
        "## EN Blocks",
        "",
    ]
    for block in en_blocks:
        digits = f" digits={block.digits}" if block.digits else ""
        lines.append(f"### EN {block.index:03d} [{block.kind}; words={block.words}{digits}]")
        lines.append(block.text)
        lines.append("")
    lines.append("## RU Blocks")
    lines.append("")
    for block in ru_blocks:
        digits = f" digits={block.digits}" if block.digits else ""
        lines.append(f"### RU {block.index:03d} [{block.kind}; words={block.words}{digits}]")
        lines.append(block.text)
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return SectionPack(
        code=code,
        en_path=str(en_path),
        ru_path=str(ru_path),
        output=str(out_path),
        en_blocks=len(en_blocks),
        ru_blocks=len(ru_blocks),
        en_words=sum(b.words for b in en_blocks),
        ru_words=sum(b.words for b in ru_blocks),
    )


def build_packs(en_dir: Path, ru_dir: Path, output_dir: Path, codes: Sequence[str]) -> List[SectionPack]:
    output_dir.mkdir(parents=True, exist_ok=True)
    packs: List[SectionPack] = []
    for code in wanted_codes(en_dir, codes):
        en_path = en_dir / f"{code}.txt"
        ru_path = ru_dir / f"{code}.docx"
        if not en_path.exists() or not ru_path.exists():
            raise SystemExit(f"ERROR: missing pair for section {code}: {en_path} / {ru_path}")
        packs.append(write_section_pack(code, en_path, ru_path, output_dir / f"{code}.md"))

    (output_dir / "index.json").write_text(
        json.dumps({"sections": [asdict(pack) for pack in packs]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Translation Review Pack Index",
        "",
        "| Code | EN blocks | RU blocks | EN words | RU words |",
        "|---|---:|---:|---:|---:|",
    ]
    for pack in packs:
        lines.append(f"| {pack.code} | {pack.en_blocks} | {pack.ru_blocks} | {pack.en_words} | {pack.ru_words} |")
    (output_dir / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return packs


def main() -> int:
    parser = argparse.ArgumentParser(description="Create side-by-side EN/RU Vibhava review packs")
    parser.add_argument("en_dir")
    parser.add_argument("ru_dir")
    parser.add_argument("output_dir")
    parser.add_argument("--sections", nargs="*", default=[], help="Optional 3-digit section codes")
    args = parser.parse_args()
    packs = build_packs(Path(args.en_dir), Path(args.ru_dir), Path(args.output_dir), args.sections)
    print(f"Wrote {len(packs)} packs to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
