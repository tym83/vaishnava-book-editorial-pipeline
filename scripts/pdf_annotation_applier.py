#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""
Apply a review issue bundle as PDF text annotations using Ghostscript pdfmark.

Examples:
  python3 pdf_annotation_applier.py apply input.pdf issues.json output.pdf
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from review_issue_utils import ISSUE_BUNDLE_VERSION, issue_body, load_json


PAGE_SIZE_RE = re.compile(r"^Page\s+(\d+)\s+size:\s+([0-9.]+)\s+x\s+([0-9.]+)\s+pts$", re.MULTILINE)


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def run_pdfinfo(pdf_path: Path) -> Dict[int, Tuple[float, float]]:
    proc = subprocess.run(
        ["pdfinfo", "-f", "1", "-l", "999999", str(pdf_path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    sizes: Dict[int, Tuple[float, float]] = {}
    for match in PAGE_SIZE_RE.finditer(proc.stdout):
        page = int(match.group(1))
        width = float(match.group(2))
        height = float(match.group(3))
        sizes[page] = (width, height)
    if not sizes:
        die(f"Could not determine page sizes via pdfinfo: {pdf_path}")
    return sizes


def pdf_hex_string(text: str) -> str:
    data = ("\ufeff" + text).encode("utf-16-be")
    return "<" + data.hex().upper() + ">"


def annotation_ps(page: int, rect: Sequence[float], title: str, contents: str) -> str:
    x1, y1, x2, y2 = rect
    return (
        "[ /Page {page} "
        "/Rect [{x1:.2f} {y1:.2f} {x2:.2f} {y2:.2f}] "
        "/Title {title} "
        "/Contents {contents} "
        "/Subtype /Text "
        "/Name /Comment "
        "/Open false "
        "/ANN pdfmark"
    ).format(
        page=page,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
        title=pdf_hex_string(title),
        contents=pdf_hex_string(contents),
    )


def build_rect(page_height: float, index_on_page: int, margin_x: float, top_margin: float, box_w: float, box_h: float, gap: float) -> List[float]:
    top = page_height - top_margin - index_on_page * gap
    bottom = max(12.0, top - box_h)
    return [margin_x, bottom, margin_x + box_w, top]


def apply_annotations(
    input_pdf: Path,
    issues_json: Path,
    output_pdf: Path,
    author: str,
    report_json: Optional[Path],
    report_md: Optional[Path],
    margin_x: float,
    top_margin: float,
    box_w: float,
    box_h: float,
    gap: float,
) -> Dict[str, object]:
    if not input_pdf.exists():
        die(f"Input PDF not found: {input_pdf}")
    bundle = load_json(issues_json)
    if bundle.get("version") != ISSUE_BUNDLE_VERSION:
        die(f"Unsupported issue bundle version: {bundle.get('version')}")
    page_sizes = run_pdfinfo(input_pdf)
    page_count = max(page_sizes)
    issues_by_page: Dict[int, List[Dict[str, object]]] = defaultdict(list)
    skipped: List[Dict[str, object]] = []

    for issue in bundle.get("issues", []):
        anchor = issue.get("anchor") or {}
        page = anchor.get("page") or issue.get("metadata", {}).get("page")
        if page is None:
            skipped.append({"id": issue.get("id"), "reason": "missing_page_anchor"})
            continue
        try:
            page_num = int(page)
        except (TypeError, ValueError):
            skipped.append({"id": issue.get("id"), "reason": f"invalid_page_anchor:{page}"})
            continue
        if page_num < 1 or page_num > page_count:
            skipped.append({"id": issue.get("id"), "reason": f"page_out_of_range:{page_num}"})
            continue
        issues_by_page[page_num].append(issue)

    ps_lines = ["%!"]
    applied: List[Dict[str, object]] = []
    for page_num in sorted(issues_by_page):
        width, height = page_sizes[page_num]
        for idx, issue in enumerate(issues_by_page[page_num]):
            anchor = issue.get("anchor") or {}
            rect = anchor.get("rect")
            if not rect or len(rect) != 4:
                rect = build_rect(height, idx, margin_x, top_margin, box_w, box_h, gap)
            ps_lines.append(annotation_ps(page_num, rect, author, issue_body(issue)))
            applied.append(
                {
                    "id": issue.get("id"),
                    "page": page_num,
                    "rect": rect,
                }
            )

    with tempfile.TemporaryDirectory(prefix="pdf-annotation-applier-") as tmp:
        ps_path = Path(tmp) / "annotations.ps"
        ps_path.write_text("\n".join(ps_lines) + "\n", encoding="utf-8")
        subprocess.run(
            [
                "gs",
                "-q",
                "-dBATCH",
                "-dNOPAUSE",
                "-sDEVICE=pdfwrite",
                f"-sOutputFile={output_pdf}",
                str(ps_path),
                str(input_pdf),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    summary = {
        "input": str(input_pdf),
        "issues": str(issues_json),
        "output": str(output_pdf),
        "author": author,
        "applied": applied,
        "skipped": skipped,
    }
    if report_json:
        report_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if report_md:
        lines = [
            "# PDF Annotation Apply Report",
            "",
            f"Input: `{input_pdf}`",
            f"Issues: `{issues_json}`",
            f"Output: `{output_pdf}`",
            "",
            f"- applied: {len(applied)}",
            f"- skipped: {len(skipped)}",
            "",
            "## Applied",
        ]
        if not applied:
            lines.append("- none")
        else:
            for item in applied[:200]:
                lines.append(f"- `{item['id']}` -> page {item['page']} rect={item['rect']}")
        lines.extend(["", "## Skipped"])
        if not skipped:
            lines.append("- none")
        else:
            for item in skipped[:200]:
                lines.append(f"- `{item['id']}` {item['reason']}")
        report_md.write_text("\n".join(lines), encoding="utf-8")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply issue bundle as PDF text annotations")
    sub = parser.add_subparsers(dest="command", required=True)

    apply_cmd = sub.add_parser("apply")
    apply_cmd.add_argument("input_pdf")
    apply_cmd.add_argument("issues_json")
    apply_cmd.add_argument("output_pdf")
    apply_cmd.add_argument("--author", default="Codex")
    apply_cmd.add_argument("--report-json")
    apply_cmd.add_argument("--report-md")
    apply_cmd.add_argument("--margin-x", type=float, default=24.0)
    apply_cmd.add_argument("--top-margin", type=float, default=24.0)
    apply_cmd.add_argument("--box-w", type=float, default=20.0)
    apply_cmd.add_argument("--box-h", type=float, default=20.0)
    apply_cmd.add_argument("--gap", type=float, default=26.0)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "apply":
        parser.error("Unknown command")
        return 2
    summary = apply_annotations(
        Path(args.input_pdf),
        Path(args.issues_json),
        Path(args.output_pdf),
        args.author,
        Path(args.report_json) if args.report_json else None,
        Path(args.report_md) if args.report_md else None,
        args.margin_x,
        args.top_margin,
        args.box_w,
        args.box_h,
        args.gap,
    )
    print(json.dumps({"applied": len(summary["applied"]), "skipped": len(summary["skipped"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
