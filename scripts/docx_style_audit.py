#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""
Audit DOCX style hygiene before InDesign import.

v1 scope:
- verify canonical paragraph and character styles are defined
- report which styles are actually used
- flag non-canonical used styles
- flag direct paragraph formatting overrides
- flag direct run formatting overrides
- flag manual italic/bold without character styles
- flag Gaura Times usage in runs/styles
- emit human-readable Markdown and structured JSON reports

Examples:
  python3 docx_style_audit.py audit in.docx
  python3 docx_style_audit.py audit in.docx --report-md audit.md --report-json audit.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from lxml import etree

from glossary_policy import contains_phrase, load_glossary_policy


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
W = f"{{{W_NS}}}"
DEFAULT_FONT = "Charis SIL"


CANONICAL_PARAGRAPH_STYLES = [
    "Заголовок 1",
    "Заголовок 2",
    "Заголовок 3",
    "Заголовок 4",
    "Шлока",
    "Перевод шлоки",
    "Цитата 1",
    "Цитата 2",
    "Шлока в цитате",
    "Письмо",
    "Источник",
    "Подпись к иллюстрации",
    "Сноска",
    "Список нумерованный 1",
    "Список нумерованный 2",
    "Список ненумерованный 1",
    "Список ненумерованный 2",
    "Основной текст",
]

CANONICAL_CHARACTER_STYLES = [
    "Char Курсив",
    "Char Полужирный",
]

SYSTEM_CHARACTER_STYLES = {
    "Endnote Reference",
    "Footnote Reference",
}

PARA_OVERRIDE_TAGS = {
    "adjustRightInd",
    "autoSpaceDE",
    "autoSpaceDN",
    "bidi",
    "cnfStyle",
    "contextualSpacing",
    "divId",
    "framePr",
    "ind",
    "jc",
    "keepLines",
    "keepNext",
    "kinsoku",
    "numPr",
    "outlineLvl",
    "pageBreakBefore",
    "rPr",
    "sectPr",
    "shd",
    "snapToGrid",
    "spacing",
    "suppressAutoHyphens",
    "suppressLineNumbers",
    "suppressOverlap",
    "tabs",
    "textAlignment",
    "textboxTightWrap",
    "topLinePunct",
    "widowControl",
    "wordWrap",
}

RUN_OVERRIDE_TAGS = {
    "b",
    "bCs",
    "caps",
    "color",
    "dstrike",
    "emboss",
    "fitText",
    "highlight",
    "i",
    "iCs",
    "imprint",
    "kern",
    "outline",
    "position",
    "rFonts",
    "shadow",
    "shd",
    "smallCaps",
    "spacing",
    "strike",
    "sz",
    "szCs",
    "u",
    "vanish",
    "vertAlign",
    "w",
}


@dataclass
class StyleInfo:
    style_id: str
    name: str
    style_type: str
    is_default: bool = False


@dataclass
class Issue:
    kind: str
    severity: str
    part: str
    paragraph_index: int
    excerpt: str
    details: dict = field(default_factory=dict)


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def convert_doc_to_docx(path: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="docx-style-audit-"))
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


def resolve_source(path: Path) -> tuple[Path, Optional[Path]]:
    if not path.exists():
        die(f"Input file not found: {path}")
    if path.suffix.lower() == ".doc":
        converted = convert_doc_to_docx(path)
        return converted, converted.parent
    if path.suffix.lower() != ".docx":
        die("docx_style_audit currently supports .docx and .doc")
    return path, None


def cleanup_temp(temp_dir: Optional[Path]) -> None:
    if temp_dir and temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)


def local_name(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def visible_text(node) -> str:
    return "".join(t.text or "" for t in node.xpath(".//w:t", namespaces=NS)).strip()


def excerpt(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def onoff_is_true(node) -> bool:
    val = node.get(f"{W}val")
    if val is None:
        return True
    return val not in {"0", "false", "False", "off"}


def parse_styles(docx_path: Path) -> Dict[str, StyleInfo]:
    with zipfile.ZipFile(docx_path, "r") as z:
        try:
            data = z.read("word/styles.xml")
        except KeyError:
            die("word/styles.xml not found in docx")
    root = etree.fromstring(data)
    styles: Dict[str, StyleInfo] = {}
    for style in root.xpath(".//w:style", namespaces=NS):
        style_id = style.get(f"{W}styleId")
        style_type = style.get(f"{W}type") or "unknown"
        is_default = style.get(f"{W}default") in {"1", "true", "True"}
        name_node = style.find("w:name", namespaces=NS)
        name = name_node.get(f"{W}val") if name_node is not None else style_id
        if style_id and name:
            styles[style_id] = StyleInfo(
                style_id=style_id,
                name=name,
                style_type=style_type,
                is_default=is_default,
            )
    return styles


def iter_story_parts(z: zipfile.ZipFile) -> Iterable[tuple[str, etree._Element]]:
    main_parts = [
        "word/document.xml",
        "word/footnotes.xml",
        "word/endnotes.xml",
        "word/comments.xml",
    ]
    for name in z.namelist():
        if name in main_parts or (
            (name.startswith("word/header") or name.startswith("word/footer")) and name.endswith(".xml")
        ):
            try:
                yield name, etree.fromstring(z.read(name))
            except etree.XMLSyntaxError:
                continue


def iter_paragraphs_for_part(part_name: str, root) -> Iterable[etree._Element]:
    if part_name == "word/document.xml":
        return root.xpath(".//w:body//w:p", namespaces=NS)
    if part_name == "word/footnotes.xml":
        return root.xpath(".//w:footnote[not(@w:type)]//w:p", namespaces=NS)
    if part_name == "word/endnotes.xml":
        return root.xpath(".//w:endnote[not(@w:type)]//w:p", namespaces=NS)
    return root.xpath(".//w:p", namespaces=NS)


def get_default_style_name(styles: Dict[str, StyleInfo], style_type: str) -> Optional[str]:
    for style in styles.values():
        if style.style_type == style_type and style.is_default:
            return style.name
    return None


def get_paragraph_style_name(p, styles: Dict[str, StyleInfo], default_name: Optional[str]) -> Optional[str]:
    p_style = p.find("w:pPr/w:pStyle", namespaces=NS)
    if p_style is None:
        return default_name
    style_id = p_style.get(f"{W}val")
    info = styles.get(style_id or "")
    return info.name if info else style_id


def get_run_style_name(r, styles: Dict[str, StyleInfo]) -> Optional[str]:
    r_style = r.find("w:rPr/w:rStyle", namespaces=NS)
    if r_style is None:
        return None
    style_id = r_style.get(f"{W}val")
    info = styles.get(style_id or "")
    return info.name if info else style_id


def paragraph_override_tags(p) -> List[str]:
    ppr = p.find("w:pPr", namespaces=NS)
    if ppr is None:
        return []
    tags = []
    for child in ppr:
        name = local_name(child.tag)
        if name == "pStyle":
            continue
        if name in PARA_OVERRIDE_TAGS:
            tags.append(name)
    return sorted(set(tags))


def run_override_tags(r) -> List[str]:
    rpr = r.find("w:rPr", namespaces=NS)
    if rpr is None:
        return []
    tags = []
    for child in rpr:
        name = local_name(child.tag)
        if name == "rStyle":
            continue
        if name in {"b", "bCs", "i", "iCs", "u", "strike", "dstrike", "caps", "smallCaps", "vanish"}:
            if not onoff_is_true(child):
                continue
        if name in RUN_OVERRIDE_TAGS:
            tags.append(name)
    return sorted(set(tags))


def run_fonts(r) -> List[str]:
    rpr = r.find("w:rPr", namespaces=NS)
    if rpr is None:
        return []
    names = []
    for rfonts in rpr.findall("w:rFonts", namespaces=NS):
        for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
            value = rfonts.get(f"{W}{attr}")
            if value:
                names.append(value)
    return sorted(set(names))


def rfonts_values(rfonts) -> Dict[str, str]:
    if rfonts is None:
        return {}
    return {
        attr: rfonts.get(f"{W}{attr}")
        for attr in ("ascii", "hAnsi", "cs", "eastAsia")
        if rfonts.get(f"{W}{attr}")
    }


def unexpected_font_attrs(values: Dict[str, str]) -> Dict[str, str]:
    expected_attrs = ("ascii", "hAnsi", "cs", "eastAsia")
    return {
        attr: values.get(attr, "<missing>")
        for attr in expected_attrs
        if values.get(attr) != DEFAULT_FONT
    }


def audit_style_fonts(docx_path: Path) -> List[Issue]:
    with zipfile.ZipFile(docx_path, "r") as z:
        try:
            root = etree.fromstring(z.read("word/styles.xml"))
        except KeyError:
            die("word/styles.xml not found in docx")

    issues: List[Issue] = []
    defaults_rfonts = root.find("w:docDefaults/w:rPrDefault/w:rPr/w:rFonts", namespaces=NS)
    defaults_bad = unexpected_font_attrs(rfonts_values(defaults_rfonts))
    if defaults_bad:
        issues.append(
            Issue(
                kind="style_unexpected_font",
                severity="warning",
                part="styles",
                paragraph_index=0,
                excerpt="docDefaults",
                details={"expected_font": DEFAULT_FONT, "fonts": defaults_bad},
            )
        )

    for style in root.xpath(".//w:style[@w:type='paragraph' or @w:type='character']", namespaces=NS):
        style_id = style.get(f"{W}styleId")
        name_node = style.find("w:name", namespaces=NS)
        name = name_node.get(f"{W}val") if name_node is not None else style_id
        values = rfonts_values(style.find("w:rPr/w:rFonts", namespaces=NS))
        bad = unexpected_font_attrs(values)
        if not bad:
            continue
        issues.append(
            Issue(
                kind="style_unexpected_font",
                severity="warning",
                part="styles",
                paragraph_index=0,
                excerpt=name or style_id or "<unnamed>",
                details={"expected_font": DEFAULT_FONT, "style_id": style_id, "fonts": bad},
            )
        )
    return issues


def run_is_italic(r_style_name: Optional[str], r_overrides: List[str]) -> bool:
    return r_style_name == "Char Курсив" or "i" in r_overrides or "iCs" in r_overrides


def audit_docx(docx_path: Path, glossary_approved: Optional[Path] = None) -> dict:
    styles = parse_styles(docx_path)
    glossary_entries = [entry for entry in load_glossary_policy(glossary_approved) if entry.italic_automation in {"always", "never"}]
    default_paragraph_style = get_default_style_name(styles, "paragraph")
    defined_paragraph_styles = sorted(
        s.name for s in styles.values() if s.style_type == "paragraph"
    )
    defined_character_styles = sorted(
        s.name for s in styles.values() if s.style_type == "character"
    )

    used_paragraph_styles = Counter()
    used_character_styles = Counter()
    direct_paragraph_overrides = Counter()
    direct_run_overrides = Counter()
    gaura_font_runs = 0
    style_font_issues = audit_style_fonts(docx_path)
    issues: List[Issue] = list(style_font_issues)

    with zipfile.ZipFile(docx_path, "r") as z:
        for part_name, root in iter_story_parts(z):
            for idx, p in enumerate(iter_paragraphs_for_part(part_name, root), 1):
                text = visible_text(p)
                p_style_name = get_paragraph_style_name(p, styles, default_paragraph_style)
                if p_style_name:
                    used_paragraph_styles[p_style_name] += 1

                p_overrides = paragraph_override_tags(p)
                if p_overrides:
                    for tag in p_overrides:
                        direct_paragraph_overrides[tag] += 1
                    issues.append(
                        Issue(
                            kind="paragraph_override",
                            severity="warning",
                            part=part_name,
                            paragraph_index=idx,
                            excerpt=excerpt(text),
                            details={"style": p_style_name, "override_tags": p_overrides},
                        )
                    )

                para_run_override_counter = Counter()
                para_manual_emphasis_counter = Counter()
                para_gaura_runs = 0
                para_character_styles = Counter()
                para_italic_fragments: List[str] = []
                italic_buffer: List[str] = []

                for run_idx, r in enumerate(p.xpath("./descendant::w:r", namespaces=NS), 1):
                    run_text = visible_text(r)
                    if not run_text.strip():
                        continue

                    r_style_name = get_run_style_name(r, styles)
                    if r_style_name:
                        used_character_styles[r_style_name] += 1
                        para_character_styles[r_style_name] += 1

                    r_overrides = run_override_tags(r)
                    if r_overrides:
                        for tag in r_overrides:
                            direct_run_overrides[tag] += 1
                            para_run_override_counter[tag] += 1

                    is_italic_run = run_is_italic(r_style_name, r_overrides)
                    if is_italic_run:
                        italic_buffer.append(run_text)
                    elif italic_buffer:
                        para_italic_fragments.append("".join(italic_buffer))
                        italic_buffer = []

                    fonts = run_fonts(r)
                    if "Gaura Times" in fonts:
                        gaura_font_runs += 1
                        para_gaura_runs += 1

                    manual_emphasis = []
                    if "i" in r_overrides or "iCs" in r_overrides:
                        if r_style_name != "Char Курсив":
                            manual_emphasis.append("italic")
                    if "b" in r_overrides or "bCs" in r_overrides:
                        if r_style_name != "Char Полужирный":
                            manual_emphasis.append("bold")
                    if manual_emphasis:
                        for item in manual_emphasis:
                            para_manual_emphasis_counter[item] += 1

                if italic_buffer:
                    para_italic_fragments.append("".join(italic_buffer))

                if para_run_override_counter:
                    issues.append(
                        Issue(
                            kind="run_override",
                            severity="warning",
                            part=part_name,
                            paragraph_index=idx,
                            excerpt=excerpt(text),
                            details={
                                "paragraph_style": p_style_name,
                                "character_styles": dict(sorted(para_character_styles.items())),
                                "override_counts": dict(sorted(para_run_override_counter.items())),
                            },
                        )
                    )

                if para_manual_emphasis_counter:
                    issues.append(
                        Issue(
                            kind="manual_emphasis_without_char_style",
                            severity="warning",
                            part=part_name,
                            paragraph_index=idx,
                            excerpt=excerpt(text),
                            details={
                                "paragraph_style": p_style_name,
                                "character_styles": dict(sorted(para_character_styles.items())),
                                "manual_emphasis_counts": dict(sorted(para_manual_emphasis_counter.items())),
                            },
                        )
                    )

                if para_gaura_runs:
                    issues.append(
                        Issue(
                            kind="gaura_times_run",
                            severity="warning",
                            part=part_name,
                            paragraph_index=idx,
                            excerpt=excerpt(text),
                            details={
                                "paragraph_style": p_style_name,
                                "character_styles": dict(sorted(para_character_styles.items())),
                                "gaura_runs": para_gaura_runs,
                            },
                        )
                    )

                if glossary_entries and text.strip():
                    for entry in glossary_entries:
                        forms = entry.search_forms()
                        if not forms:
                            continue
                        if entry.italic_automation == "always":
                            if not any(contains_phrase(text, form, ignore_case=True) for form in forms):
                                continue
                            if any(
                                contains_phrase(fragment, form, ignore_case=True)
                                for fragment in para_italic_fragments
                                for form in forms
                            ):
                                continue
                            issues.append(
                                Issue(
                                    kind="glossary_expected_italic",
                                    severity="warning",
                                    part=part_name,
                                    paragraph_index=idx,
                                    excerpt=excerpt(text),
                                    details={
                                        "paragraph_style": p_style_name,
                                        "approved_form": entry.approved_form,
                                        "matched_forms": forms,
                                        "italic_fragments": para_italic_fragments,
                                        "glossary_entry_id": entry.entry_id,
                                    },
                                )
                            )
                        elif entry.italic_automation == "never":
                            if not any(
                                contains_phrase(fragment, form, ignore_case=True)
                                for fragment in para_italic_fragments
                                for form in forms
                            ):
                                continue
                            issues.append(
                                Issue(
                                    kind="glossary_expected_roman",
                                    severity="warning",
                                    part=part_name,
                                    paragraph_index=idx,
                                    excerpt=excerpt(text),
                                    details={
                                        "paragraph_style": p_style_name,
                                        "approved_form": entry.approved_form,
                                        "matched_forms": forms,
                                        "italic_fragments": para_italic_fragments,
                                        "glossary_entry_id": entry.entry_id,
                                    },
                                )
                            )

    missing_paragraph_styles = [
        name for name in CANONICAL_PARAGRAPH_STYLES if name not in defined_paragraph_styles
    ]
    missing_character_styles = [
        name for name in CANONICAL_CHARACTER_STYLES if name not in defined_character_styles
    ]
    noncanonical_used_paragraph_styles = sorted(
        name for name in used_paragraph_styles if name and name not in CANONICAL_PARAGRAPH_STYLES
    )
    noncanonical_used_character_styles = sorted(
        name
        for name in used_character_styles
        if name and name not in CANONICAL_CHARACTER_STYLES and name not in SYSTEM_CHARACTER_STYLES
    )

    for name in noncanonical_used_paragraph_styles:
        issues.append(
            Issue(
                kind="noncanonical_paragraph_style",
                severity="warning",
                part="styles",
                paragraph_index=0,
                excerpt=name,
                details={"style": name, "count": used_paragraph_styles[name]},
            )
        )
    for name in noncanonical_used_character_styles:
        issues.append(
            Issue(
                kind="noncanonical_character_style",
                severity="warning",
                part="styles",
                paragraph_index=0,
                excerpt=name,
                details={"style": name, "count": used_character_styles[name]},
            )
        )

    return {
        "file": str(docx_path),
        "defined_paragraph_styles": defined_paragraph_styles,
        "defined_character_styles": defined_character_styles,
        "missing_paragraph_styles": missing_paragraph_styles,
        "missing_character_styles": missing_character_styles,
        "used_paragraph_styles": dict(sorted(used_paragraph_styles.items())),
        "used_character_styles": dict(sorted(used_character_styles.items())),
        "noncanonical_used_paragraph_styles": noncanonical_used_paragraph_styles,
        "noncanonical_used_character_styles": noncanonical_used_character_styles,
        "direct_paragraph_overrides": dict(sorted(direct_paragraph_overrides.items())),
        "direct_run_overrides": dict(sorted(direct_run_overrides.items())),
        "style_font_issues": [asdict(issue) for issue in style_font_issues],
        "gaura_font_runs": gaura_font_runs,
        "glossary_policy_entries": len(glossary_entries),
        "issues": [asdict(issue) for issue in issues],
    }


def write_markdown_report(result: dict, out_path: Path, max_issue_lines: int = 200) -> None:
    lines: List[str] = []
    lines.append(f"# DOCX Style Audit\n")
    lines.append(f"File: `{result['file']}`\n")

    def add_list(title: str, items: List[str]) -> None:
        lines.append(f"## {title}\n")
        if not items:
            lines.append("- none\n")
            return
        for item in items:
            lines.append(f"- {item}\n")

    def add_counter(title: str, data: Dict[str, int]) -> None:
        lines.append(f"## {title}\n")
        if not data:
            lines.append("- none\n")
            return
        for key, value in data.items():
            lines.append(f"- `{key}`: {value}\n")

    add_list("Missing Paragraph Styles", result["missing_paragraph_styles"])
    add_list("Missing Character Styles", result["missing_character_styles"])
    add_list("Noncanonical Used Paragraph Styles", result["noncanonical_used_paragraph_styles"])
    add_list("Noncanonical Used Character Styles", result["noncanonical_used_character_styles"])
    add_counter("Used Paragraph Styles", result["used_paragraph_styles"])
    add_counter("Used Character Styles", result["used_character_styles"])
    add_counter("Direct Paragraph Overrides", result["direct_paragraph_overrides"])
    add_counter("Direct Run Overrides", result["direct_run_overrides"])
    lines.append("## Style Font Issues\n")
    if not result.get("style_font_issues"):
        lines.append("- none\n")
    else:
        for issue in result["style_font_issues"]:
            details = json.dumps(issue["details"], ensure_ascii=False, sort_keys=True)
            lines.append(f"- `{issue['excerpt']}` {details}\n")
    lines.append("## Gaura Times Runs\n")
    lines.append(f"- {result['gaura_font_runs']}\n")
    lines.append("## Glossary Policy Entries\n")
    lines.append(f"- {result.get('glossary_policy_entries', 0)}\n")

    lines.append("## Issues\n")
    issues = result["issues"]
    if not issues:
        lines.append("- none\n")
    else:
        for issue in issues[:max_issue_lines]:
            details = json.dumps(issue["details"], ensure_ascii=False, sort_keys=True)
            lines.append(
                f"- `{issue['kind']}` [{issue['severity']}] "
                f"{issue['part']}#{issue['paragraph_index']}: "
                f"`{issue['excerpt']}` {details}\n"
            )
        hidden = len(issues) - min(len(issues), max_issue_lines)
        if hidden > 0:
            lines.append(f"- ... {hidden} more issues omitted\n")

    out_path.write_text("".join(lines), encoding="utf-8")


def print_summary(result: dict) -> None:
    print(f"File: {result['file']}")
    print(f"Missing paragraph styles: {len(result['missing_paragraph_styles'])}")
    print(f"Missing character styles: {len(result['missing_character_styles'])}")
    print(f"Used paragraph styles: {len(result['used_paragraph_styles'])}")
    print(f"Used character styles: {len(result['used_character_styles'])}")
    print(f"Direct paragraph override tags: {sum(result['direct_paragraph_overrides'].values())}")
    print(f"Direct run override tags: {sum(result['direct_run_overrides'].values())}")
    print(f"Style font issues: {len(result.get('style_font_issues', []))}")
    print(f"Gaura Times runs: {result['gaura_font_runs']}")
    print(f"Glossary policy entries: {result.get('glossary_policy_entries', 0)}")
    print(f"Issues: {len(result['issues'])}")


def cmd_audit(args) -> None:
    src, temp_dir = resolve_source(Path(args.input))
    try:
        result = audit_docx(src, glossary_approved=Path(args.glossary_approved) if args.glossary_approved else None)
        print_summary(result)
        if args.report_json:
            Path(args.report_json).write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if args.report_md:
            write_markdown_report(result, Path(args.report_md), max_issue_lines=args.max_issue_lines)
    finally:
        cleanup_temp(temp_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit DOCX style hygiene before InDesign import")
    sub = parser.add_subparsers(dest="cmd", required=True)

    audit = sub.add_parser("audit")
    audit.add_argument("input")
    audit.add_argument("--glossary-approved")
    audit.add_argument("--report-md")
    audit.add_argument("--report-json")
    audit.add_argument("--max-issue-lines", type=int, default=200)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.cmd == "audit":
        cmd_audit(args)
    else:
        parser.error(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
