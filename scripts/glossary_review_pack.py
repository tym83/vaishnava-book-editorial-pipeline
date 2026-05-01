#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""
Prepare a structured glossary review pack from glossary seed/conflicts.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def normalize_key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def infer_suggested_action(row: dict[str, str], has_conflict: bool) -> tuple[str, str]:
    text = row.get("approved_form", "")
    category = row.get("category", "")
    italic = row.get("italic_required", "")
    diacritics = row.get("diacritics_policy", "")

    if re.match(r"^[а-яё]\s", text.lower()):
        return "drop", "high"
    if re.search(r"^[\[(,;:.\-–—]", text):
        return "drop", "high"
    if text.count(" ") >= 4 and category == "other":
        return "drop", "medium"
    if "needs_review" in row.get("status", "") or has_conflict:
        if category in {"personal_name", "place_name", "scripture_title", "philosophical_term", "honorific"}:
            return "review", "high"
        return "review", "medium"
    if category in {"personal_name", "place_name", "scripture_title", "philosophical_term", "honorific"}:
        return "keep", "medium"
    if italic == "conditional" or diacritics == "needs_review":
        return "review", "medium"
    return "review", "low"


def make_review_row(seed_row: dict[str, str], conflict_map: dict[str, dict[str, str]]) -> dict[str, str]:
    key = normalize_key(seed_row.get("approved_form", ""))
    conflict_row = conflict_map.get(key, {})
    has_conflict = bool(conflict_row)
    suggested_action, priority = infer_suggested_action(seed_row, has_conflict)

    out = dict(seed_row)
    out["normalized_key"] = key
    out["conflict_flag"] = "yes" if has_conflict else "no"
    out["conflict_variants"] = conflict_row.get("variants", "")
    out["conflict_sources"] = conflict_row.get("sources", "")
    out["review_priority"] = priority
    out["suggested_action"] = suggested_action
    out["decision"] = ""
    out["approved_form_override"] = ""
    out["category_override"] = ""
    out["italic_required_override"] = ""
    out["diacritics_policy_override"] = ""
    out["merge_into"] = ""
    out["review_notes"] = ""
    return out


def write_summary(path: Path, rows: list[dict[str, str]]) -> None:
    action_counts = Counter(row["suggested_action"] for row in rows)
    priority_counts = Counter(row["review_priority"] for row in rows)
    category_counts = Counter(row["category"] for row in rows)

    lines = []
    lines.append("# Glossary Review Pack")
    lines.append("")
    lines.append(f"- total rows: {len(rows)}")
    lines.append("")
    lines.append("## Suggested actions")
    for key, value in action_counts.most_common():
        lines.append(f"- `{key}`: {value}")
    lines.append("")
    lines.append("## Review priority")
    for key, value in priority_counts.most_common():
        lines.append(f"- `{key}`: {value}")
    lines.append("")
    lines.append("## Categories")
    for key, value in category_counts.most_common():
        lines.append(f"- `{key}`: {value}")
    lines.append("")
    lines.append("## How to use")
    lines.append("1. Start with `glossary_review_master.csv`.")
    lines.append("2. Fill `decision` for each row: `keep`, `drop`, `rename`, `merge`, `reclassify`, `defer`.")
    lines.append("3. Use override columns only when the current auto-choice is wrong.")
    lines.append("4. If `decision=merge`, fill `merge_into` with the target approved form.")
    lines.append("5. If `decision=rename`, fill `approved_form_override`.")
    lines.append("6. Then run `glossary_apply_review.py`.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_priority_markdown(path: Path, rows: list[dict[str, str]]) -> None:
    lines = []
    lines.append("# Glossary High-Priority Review")
    lines.append("")
    lines.append(f"- rows: {len(rows)}")
    lines.append("- decision values: `keep`, `drop`, `rename`, `merge`, `reclassify`, `defer`")
    lines.append("")

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["category"]].append(row)

    for category in sorted(grouped):
        lines.append(f"## {category}")
        lines.append("")
        for row in grouped[category]:
            lines.append(f"### {row['approved_form']}")
            lines.append(f"- `id`: `{row['id']}`")
            lines.append(f"- `suggested_action`: `{row['suggested_action']}`")
            lines.append(f"- `review_priority`: `{row['review_priority']}`")
            lines.append(f"- `conflict_flag`: `{row['conflict_flag']}`")
            if row.get("conflict_variants"):
                lines.append(f"- `conflict_variants`: {row['conflict_variants']}")
            if row.get("source_examples"):
                lines.append(f"- `examples`: {row['source_examples']}")
            lines.append(f"- decision: {row['suggested_action'] if row['suggested_action'] != 'review' else 'keep'}")
            lines.append("- approved_form:")
            lines.append(f"- category: {row['category']}")
            lines.append("- merge_into:")
            lines.append("- notes:")
            lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_prepare(args) -> int:
    seed_rows = read_csv(Path(args.seed).expanduser())
    conflict_rows = read_csv(Path(args.conflicts).expanduser())

    conflict_map = {
        normalize_key(row.get("approved_form", "")): row
        for row in conflict_rows
        if row.get("approved_form")
    }

    review_rows = [make_review_row(row, conflict_map) for row in seed_rows]

    fieldnames = [
        "id",
        "normalized_key",
        "lemma_ru",
        "lemma_en",
        "category",
        "approved_form",
        "declension_notes",
        "italic_required",
        "diacritics_policy",
        "capitalization_notes",
        "variants_found",
        "preferred_source",
        "source_examples",
        "editor_decision",
        "status",
        "notes",
        "conflict_flag",
        "conflict_variants",
        "conflict_sources",
        "review_priority",
        "suggested_action",
        "decision",
        "approved_form_override",
        "category_override",
        "italic_required_override",
        "diacritics_policy_override",
        "merge_into",
        "review_notes",
    ]

    outdir = Path(args.output_dir).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)

    master_csv = outdir / "glossary_review_master.csv"
    write_csv(master_csv, review_rows, fieldnames)
    high_priority_rows = [row for row in review_rows if row["review_priority"] == "high"]
    write_csv(outdir / "glossary_review_priority_high.csv", high_priority_rows, fieldnames)
    write_priority_markdown(outdir / "glossary_review_priority_high.md", high_priority_rows)

    by_category: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in review_rows:
        by_category[row["category"]].append(row)
    for category, rows in by_category.items():
        safe_category = re.sub(r"[^a-z0-9_]+", "_", category.lower())
        write_csv(outdir / "by_category" / f"{safe_category}.csv", rows, fieldnames)

    write_summary(outdir / "glossary_review_summary.md", review_rows)

    print(f"Master review file: {master_csv}")
    print(f"High priority review file: {outdir / 'glossary_review_priority_high.csv'}")
    print(f"High priority review sheet: {outdir / 'glossary_review_priority_high.md'}")
    print(f"Category files: {outdir / 'by_category'}")
    print(f"Summary: {outdir / 'glossary_review_summary.md'}")
    print(f"Rows: {len(review_rows)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare a review pack from glossary seed/conflicts")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prepare = sub.add_parser("prepare", help="Prepare glossary review pack")
    p_prepare.add_argument("--seed", required=True, help="Path to glossary_seed_high_signal.csv")
    p_prepare.add_argument("--conflicts", required=True, help="Path to glossary_conflicts.csv")
    p_prepare.add_argument("--output-dir", required=True, help="Output directory")
    p_prepare.set_defaults(func=cmd_prepare)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
