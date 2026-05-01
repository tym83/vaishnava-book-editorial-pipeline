#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""
Build approved glossary artifacts from completed glossary review master CSV.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
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


def normalize_decision(row: dict[str, str]) -> str:
    return (row.get("decision") or "").strip().lower()


def apply_row_overrides(row: dict[str, str]) -> dict[str, str]:
    out = dict(row)
    if row.get("approved_form_override"):
        out["approved_form"] = row["approved_form_override"].strip()
        out["lemma_ru"] = row["approved_form_override"].strip()
    if row.get("category_override"):
        out["category"] = row["category_override"].strip()
    if row.get("italic_required_override"):
        out["italic_required"] = row["italic_required_override"].strip()
    if row.get("diacritics_policy_override"):
        out["diacritics_policy"] = row["diacritics_policy_override"].strip()
    return out


def merge_rows(target_form: str, rows: list[dict[str, str]]) -> dict[str, str]:
    base = dict(rows[0])
    base["approved_form"] = target_form
    base["lemma_ru"] = target_form
    base["status"] = "approved"
    base["editor_decision"] = "approved_by_review"

    variants = []
    examples = []
    sources = []
    notes = []
    for row in rows:
        if row.get("variants_found"):
            variants.append(row["variants_found"])
        if row.get("source_examples"):
            examples.append(row["source_examples"])
        if row.get("preferred_source"):
            sources.append(row["preferred_source"])
        if row.get("review_notes"):
            notes.append(row["review_notes"])

    base["variants_found"] = " | ".join(dict.fromkeys(variants))
    base["source_examples"] = " | ".join(dict.fromkeys(examples))
    base["preferred_source"] = " | ".join(dict.fromkeys(sources))
    base["notes"] = " | ".join(x for x in [base.get("notes", "")] + notes if x)
    return base


def cmd_apply(args) -> int:
    rows = read_csv(Path(args.review).expanduser())

    approved_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    dropped_rows: list[dict[str, str]] = []
    pending_rows: list[dict[str, str]] = []
    alias_rows: list[dict[str, str]] = []

    for row in rows:
        decision = normalize_decision(row)
        if not decision or decision == "defer":
            pending_rows.append(row)
            continue
        if decision == "drop":
            dropped_rows.append(row)
            continue

        row2 = apply_row_overrides(row)
        if decision == "merge":
            target = (row.get("merge_into") or "").strip()
            if not target:
                pending_rows.append(row)
                continue
            alias_rows.append(
                {
                    "source_form": row2.get("approved_form", ""),
                    "target_form": target,
                    "notes": row.get("review_notes", ""),
                }
            )
            approved_groups[target].append(row2)
            continue

        if decision in {"keep", "rename", "reclassify"}:
            approved_groups[row2["approved_form"]].append(row2)
            continue

        pending_rows.append(row)

    approved_rows: list[dict[str, str]] = []
    for target_form, group in sorted(approved_groups.items()):
        approved_rows.append(merge_rows(target_form, group))

    approved_fields = [
        "id",
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
    ]
    alias_fields = ["source_form", "target_form", "notes"]

    outdir = Path(args.output_dir).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)

    write_csv(outdir / "glossary_approved.csv", approved_rows, approved_fields)
    write_csv(outdir / "glossary_dropped.csv", dropped_rows, list(rows[0].keys()) if rows else [])
    write_csv(outdir / "glossary_pending_review.csv", pending_rows, list(rows[0].keys()) if rows else [])
    write_csv(outdir / "glossary_aliases.csv", alias_rows, alias_fields)

    print(f"Approved: {outdir / 'glossary_approved.csv'}")
    print(f"Dropped: {outdir / 'glossary_dropped.csv'}")
    print(f"Pending: {outdir / 'glossary_pending_review.csv'}")
    print(f"Aliases: {outdir / 'glossary_aliases.csv'}")
    print(f"Approved rows: {len(approved_rows)}")
    print(f"Pending rows: {len(pending_rows)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply glossary review decisions")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_apply = sub.add_parser("apply", help="Build approved glossary from completed review CSV")
    p_apply.add_argument("--review", required=True, help="Path to glossary_review_master.csv")
    p_apply.add_argument("--output-dir", required=True, help="Output directory")
    p_apply.set_defaults(func=cmd_apply)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
