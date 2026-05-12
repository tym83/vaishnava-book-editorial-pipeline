#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Helpers for loading manually curated glossary policy CSV files."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


def split_pipe_values(value: str) -> List[str]:
    return [item.strip() for item in str(value or "").split("|") if item.strip()]


def contains_phrase(text: str, phrase: str, *, ignore_case: bool = True) -> bool:
    normalized_text = " ".join(str(text or "").split())
    normalized_phrase = " ".join(str(phrase or "").split())
    if not normalized_text or not normalized_phrase:
        return False
    flags = re.IGNORECASE if ignore_case else 0
    pattern = rf"(?<!\w){re.escape(normalized_phrase)}(?!\w)"
    return re.search(pattern, normalized_text, flags=flags) is not None


@dataclass
class GlossaryPolicyEntry:
    entry_id: str
    approved_form: str
    category: str
    lemma_en_forms: List[str]
    allowed_forms: List[str]
    discouraged_forms: List[str]
    italic_required: str
    italic_automation: str
    diacritics_policy: str
    capitalization_notes: str
    notes: str

    def search_forms(self) -> List[str]:
        forms: List[str] = []
        for value in [self.approved_form, *self.allowed_forms]:
            if value and value not in forms:
                forms.append(value)
        return forms


def load_glossary_policy(path: Optional[Path]) -> List[GlossaryPolicyEntry]:
    if path is None:
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        rows = csv.DictReader(fh)
        entries: List[GlossaryPolicyEntry] = []
        for row in rows:
            approved_form = str(row.get("approved_form", "")).strip()
            if not approved_form:
                continue
            entries.append(
                GlossaryPolicyEntry(
                    entry_id=str(row.get("id", "")).strip(),
                    approved_form=approved_form,
                    category=str(row.get("category", "")).strip().lower(),
                    lemma_en_forms=split_pipe_values(str(row.get("lemma_en", ""))),
                    allowed_forms=split_pipe_values(str(row.get("allowed_forms", ""))),
                    discouraged_forms=split_pipe_values(str(row.get("discouraged_forms", ""))),
                    italic_required=str(row.get("italic_required", "")).strip().lower(),
                    italic_automation=str(row.get("italic_automation", "")).strip().lower() or "skip",
                    diacritics_policy=str(row.get("diacritics_policy", "")).strip(),
                    capitalization_notes=str(row.get("capitalization_notes", "")).strip(),
                    notes=str(row.get("notes", "")).strip(),
                )
            )
    return entries
