#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""Enforce canonical DOCX style geometry and remove direct formatting overrides."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, Iterable, Optional

from lxml import etree


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
W = f"{{{W_NS}}}"

CANONICAL_CHARACTER_STYLES = {"Char Курсив", "Char Полужирный"}
KEEP_CHARACTER_STYLES = CANONICAL_CHARACTER_STYLES | {"footnote reference", "endnote reference"}
DEFAULT_FONT = "Charis SIL"

STYLE_RULES = {
    "Шлока": {"left_cm": 2.0, "center": True, "italic": True},
    "Шлока в цитате": {"left_cm": 3.0, "center": True, "italic": True},
    "Перевод шлоки": {"left_cm": 2.0},
    "Цитата 1": {"left_cm": 2.0},
    "Цитата 2": {"left_cm": 3.0},
}

CANONICAL_PARAGRAPH_STYLES = {
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
}


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def cm_to_twips(value: float) -> str:
    return str(round(value / 2.54 * 1440))


def convert_doc_to_docx(path: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="docx-style-enforcer-"))
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
        die("docx_style_enforcer currently supports .docx and .doc")
    return path, None


def cleanup_temp(temp_dir: Optional[Path]) -> None:
    if temp_dir and temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)


def local_name(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def onoff_is_true(node) -> bool:
    if node is None:
        return False
    val = node.get(f"{W}val")
    if val is None:
        return True
    return val not in {"0", "false", "False", "off"}


class StyleCatalog:
    def __init__(self, root):
        self.root = root
        self.by_id: Dict[str, etree._Element] = {}
        self.by_name: Dict[str, etree._Element] = {}
        self.default_by_type: Dict[str, etree._Element] = {}
        self._rebuild()

    def _rebuild(self) -> None:
        self.by_id.clear()
        self.by_name.clear()
        self.default_by_type.clear()
        for style in self.root.xpath(".//w:style", namespaces=NS):
            style_id = style.get(f"{W}styleId")
            style_type = style.get(f"{W}type") or "unknown"
            name_node = style.find("w:name", namespaces=NS)
            name = name_node.get(f"{W}val") if name_node is not None else style_id
            if style_id:
                self.by_id[style_id] = style
            if name:
                self.by_name[name] = style
            if style.get(f"{W}default") in {"1", "true", "True"} and style_type not in self.default_by_type:
                self.default_by_type[style_type] = style

    def style_name(self, style_id: Optional[str]) -> Optional[str]:
        if not style_id:
            return None
        style = self.by_id.get(style_id)
        if style is None:
            return style_id
        name_node = style.find("w:name", namespaces=NS)
        return name_node.get(f"{W}val") if name_node is not None else style_id

    def _unique_style_id(self, style_type: str, base: str) -> str:
        prefix = "P" if style_type == "paragraph" else "C"
        stem = "".join(ch for ch in base if ch.isalnum())[:16] or "Style"
        candidate = f"{prefix}_{stem}"
        idx = 1
        while candidate in self.by_id:
            idx += 1
            candidate = f"{prefix}_{stem}_{idx}"
        return candidate

    def ensure_style(self, target_name: str, style_type: str, base_name: Optional[str] = None) -> str:
        existing = self.by_name.get(target_name)
        if existing is not None:
            return existing.get(f"{W}styleId")

        base = self.by_name.get(base_name) if base_name else None
        if base is None:
            base = self.default_by_type.get(style_type)
        if base is None:
            die(f"No base style available to create {target_name}")

        style = etree.fromstring(etree.tostring(base))
        style_id = self._unique_style_id(style_type, target_name)
        style.set(f"{W}styleId", style_id)
        style.set(f"{W}type", style_type)
        style.attrib.pop(f"{W}default", None)
        style.set(f"{W}customStyle", "1")
        name_node = style.find("w:name", namespaces=NS)
        if name_node is None:
            name_node = etree.Element(f"{W}name")
            style.insert(0, name_node)
        name_node.set(f"{W}val", target_name)
        self.root.append(style)
        self._rebuild()
        return style_id

    def style_has_italic(self, style_id: Optional[str]) -> bool:
        style = self.by_id.get(style_id or "")
        if style is None:
            return False
        return any(onoff_is_true(style.find(f"w:rPr/w:{tag}", namespaces=NS)) for tag in ("i", "iCs"))

    def style_has_bold(self, style_id: Optional[str]) -> bool:
        style = self.by_id.get(style_id or "")
        if style is None:
            return False
        return any(onoff_is_true(style.find(f"w:rPr/w:{tag}", namespaces=NS)) for tag in ("b", "bCs"))


def ensure_child(parent, tag_name: str):
    node = parent.find(f"w:{tag_name}", namespaces=NS)
    if node is None:
        node = etree.Element(f"{W}{tag_name}")
        parent.append(node)
    return node


def clear_children(parent, tag_names: Iterable[str]) -> None:
    for tag_name in tag_names:
        for node in parent.findall(f"w:{tag_name}", namespaces=NS):
            parent.remove(node)


def set_run_font(rpr, font_name: str = DEFAULT_FONT) -> None:
    rfonts = rpr.find("w:rFonts", namespaces=NS)
    if rfonts is None:
        rfonts = etree.Element(f"{W}rFonts")
        rpr.insert(0, rfonts)
    for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
        rfonts.set(f"{W}{attr}", font_name)


def configure_doc_defaults(styles_root) -> None:
    defaults = styles_root.find("w:docDefaults", namespaces=NS)
    if defaults is None:
        defaults = etree.Element(f"{W}docDefaults")
        styles_root.insert(0, defaults)
    rpr_default = defaults.find("w:rPrDefault", namespaces=NS)
    if rpr_default is None:
        rpr_default = etree.Element(f"{W}rPrDefault")
        defaults.insert(0, rpr_default)
    rpr = rpr_default.find("w:rPr", namespaces=NS)
    if rpr is None:
        rpr = etree.Element(f"{W}rPr")
        rpr_default.insert(0, rpr)
    set_run_font(rpr)


def configure_all_style_fonts(styles_root) -> int:
    updated = 0
    for style in styles_root.xpath(".//w:style[@w:type='paragraph' or @w:type='character']", namespaces=NS):
        set_run_font(ensure_child(style, "rPr"))
        updated += 1
    return updated


def configure_character_styles(catalog: StyleCatalog) -> Dict[str, str]:
    ids = {
        "Char Курсив": catalog.ensure_style("Char Курсив", "character", base_name="Default Paragraph Font"),
        "Char Полужирный": catalog.ensure_style("Char Полужирный", "character", base_name="Default Paragraph Font"),
    }
    for name, style_id in ids.items():
        style = catalog.by_id[style_id]
        rpr = ensure_child(style, "rPr")
        set_run_font(rpr)
        clear_children(rpr, ["i", "iCs", "b", "bCs"])
        if name == "Char Курсив":
            rpr.append(etree.Element(f"{W}i"))
            rpr.append(etree.Element(f"{W}iCs"))
        elif name == "Char Полужирный":
            rpr.append(etree.Element(f"{W}b"))
            rpr.append(etree.Element(f"{W}bCs"))
    return ids


def paragraph_style_rules(catalog: StyleCatalog) -> Dict[str, Dict[str, object]]:
    rules = dict(STYLE_RULES)
    for style_name in catalog.by_name:
        quote_match = re.fullmatch(r"Цитата\s+(\d+)", style_name)
        if quote_match:
            level = int(quote_match.group(1))
            rules[style_name] = {"left_cm": 1.0 + level}
            continue
        shloka_quote_match = re.fullmatch(r"Шлока в цитате\s+(\d+)", style_name)
        if shloka_quote_match:
            level = int(shloka_quote_match.group(1))
            rules[style_name] = {"left_cm": 1.0 + level, "center": True, "italic": True}
    return rules


def configure_paragraph_styles(catalog: StyleCatalog) -> Dict[str, int]:
    updated: Dict[str, int] = {}
    for style_name in CANONICAL_PARAGRAPH_STYLES:
        style = catalog.by_name.get(style_name)
        if style is not None:
            set_run_font(ensure_child(style, "rPr"))
            updated[style_name] = 1
    for style_name, rule in paragraph_style_rules(catalog).items():
        style_id = catalog.ensure_style(style_name, "paragraph", base_name="Normal")
        style = catalog.by_id[style_id]
        ppr = ensure_child(style, "pPr")
        clear_children(ppr, ["ind", "jc"])
        ind = etree.Element(f"{W}ind")
        ind.set(f"{W}left", cm_to_twips(float(rule["left_cm"])))
        ind.set(f"{W}firstLine", "0")
        ppr.append(ind)
        if rule.get("center"):
            jc = etree.Element(f"{W}jc")
            jc.set(f"{W}val", "center")
            ppr.append(jc)

        rpr = ensure_child(style, "rPr")
        set_run_font(rpr)
        clear_children(rpr, ["i", "iCs"])
        if rule.get("italic"):
            rpr.append(etree.Element(f"{W}i"))
            rpr.append(etree.Element(f"{W}iCs"))
        updated[style_name] = 1
    return updated


def iter_story_part_names(z: zipfile.ZipFile) -> Iterable[str]:
    for name in z.namelist():
        if name == "word/document.xml":
            yield name
        elif name in {"word/footnotes.xml", "word/endnotes.xml", "word/comments.xml"}:
            yield name
        elif (name.startswith("word/header") or name.startswith("word/footer")) and name.endswith(".xml"):
            yield name


def cleanup_paragraph_properties(root) -> Dict[str, int]:
    removed: Dict[str, int] = {}
    for ppr in root.xpath(".//w:pPr", namespaces=NS):
        for child in list(ppr):
            name = local_name(child.tag)
            if name in {"pStyle", "sectPr"}:
                continue
            ppr.remove(child)
            removed[name] = removed.get(name, 0) + 1
        if len(ppr) == 0:
            parent = ppr.getparent()
            if parent is not None:
                parent.remove(ppr)
    return removed


def cleanup_run_properties(root, catalog: StyleCatalog, canonical_char_ids: Dict[str, str]) -> dict:
    removed: Dict[str, int] = {}
    mapped_styles: Dict[str, int] = {}
    removed_styles: Dict[str, int] = {}

    for rpr in root.xpath(".//w:rPr", namespaces=NS):
        rstyle = rpr.find("w:rStyle", namespaces=NS)
        keep_style_id: Optional[str] = None
        if rstyle is not None:
            old_style_id = rstyle.get(f"{W}val")
            old_style_name = catalog.style_name(old_style_id) or old_style_id or ""
            if old_style_name in KEEP_CHARACTER_STYLES:
                keep_style_id = old_style_id
            elif catalog.style_has_italic(old_style_id) and not catalog.style_has_bold(old_style_id):
                keep_style_id = canonical_char_ids["Char Курсив"]
                mapped_styles[f"{old_style_name}->Char Курсив"] = mapped_styles.get(f"{old_style_name}->Char Курсив", 0) + 1
            elif catalog.style_has_bold(old_style_id) and not catalog.style_has_italic(old_style_id):
                keep_style_id = canonical_char_ids["Char Полужирный"]
                mapped_styles[f"{old_style_name}->Char Полужирный"] = mapped_styles.get(f"{old_style_name}->Char Полужирный", 0) + 1
            else:
                removed_styles[old_style_name] = removed_styles.get(old_style_name, 0) + 1

        for child in list(rpr):
            name = local_name(child.tag)
            if name == "rStyle":
                continue
            rpr.remove(child)
            removed[name] = removed.get(name, 0) + 1

        rstyle = rpr.find("w:rStyle", namespaces=NS)
        if keep_style_id:
            if rstyle is None:
                rstyle = etree.Element(f"{W}rStyle")
                rpr.insert(0, rstyle)
            rstyle.set(f"{W}val", keep_style_id)
        elif rstyle is not None:
            rpr.remove(rstyle)

        if len(rpr) == 0:
            parent = rpr.getparent()
            if parent is not None:
                parent.remove(rpr)

    return {
        "removed_run_properties": removed,
        "mapped_character_styles": mapped_styles,
        "removed_character_styles": removed_styles,
    }


def enforce_docx(src: Path, out: Path, report_json: Optional[Path] = None, report_md: Optional[Path] = None) -> dict:
    with zipfile.ZipFile(src, "r") as zin:
        styles_root = etree.fromstring(zin.read("word/styles.xml"))
        configure_doc_defaults(styles_root)
        updated_style_fonts = configure_all_style_fonts(styles_root)
        catalog = StyleCatalog(styles_root)
        canonical_char_ids = configure_character_styles(catalog)
        updated_paragraph_styles = configure_paragraph_styles(catalog)

        part_roots: Dict[str, etree._Element] = {}
        for name in iter_story_part_names(zin):
            try:
                part_roots[name] = etree.fromstring(zin.read(name))
            except etree.XMLSyntaxError:
                continue

        removed_paragraph_properties: Dict[str, int] = {}
        run_cleanup = {
            "removed_run_properties": {},
            "mapped_character_styles": {},
            "removed_character_styles": {},
        }
        for root in part_roots.values():
            for key, value in cleanup_paragraph_properties(root).items():
                removed_paragraph_properties[key] = removed_paragraph_properties.get(key, 0) + value
            part_run_cleanup = cleanup_run_properties(root, catalog, canonical_char_ids)
            for bucket, values in part_run_cleanup.items():
                for key, value in values.items():
                    run_cleanup[bucket][key] = run_cleanup[bucket].get(key, 0) + value

        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(src, "r") as zin2, zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for info in zin2.infolist():
                data = zin2.read(info.filename)
                if info.filename == "word/styles.xml":
                    data = etree.tostring(styles_root, xml_declaration=True, encoding="UTF-8", standalone="yes")
                elif info.filename in part_roots:
                    data = etree.tostring(part_roots[info.filename], xml_declaration=True, encoding="UTF-8", standalone="yes")
                zout.writestr(info, data)

    summary = {
        "input": str(src),
        "output": str(out),
        "updated_style_fonts": updated_style_fonts,
        "updated_paragraph_styles": sorted(updated_paragraph_styles),
        "removed_paragraph_properties": removed_paragraph_properties,
        **run_cleanup,
    }
    if report_json:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report_md:
        write_report_md(report_md, summary)
    return summary


def write_report_md(path: Path, summary: dict) -> None:
    lines = [
        "# DOCX Style Enforcer",
        "",
        f"- input: `{summary['input']}`",
        f"- output: `{summary['output']}`",
        f"- updated paragraph/character style fonts: {summary.get('updated_style_fonts', 0)}",
        f"- updated paragraph styles: {', '.join(summary['updated_paragraph_styles'])}",
        "",
        "## Removed Paragraph Properties",
        "",
    ]
    for key, value in sorted(summary["removed_paragraph_properties"].items()):
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Removed Run Properties", ""])
    for key, value in sorted(summary["removed_run_properties"].items()):
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Character Style Mapping", ""])
    for key, value in sorted(summary["mapped_character_styles"].items()):
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Removed Character Styles", ""])
    for key, value in sorted(summary["removed_character_styles"].items()):
        lines.append(f"- `{key}`: {value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_enforce(args) -> None:
    src, temp_dir = resolve_source(Path(args.input))
    try:
        summary = enforce_docx(
            src,
            Path(args.output),
            report_json=Path(args.report_json) if args.report_json else None,
            report_md=Path(args.report_md) if args.report_md else None,
        )
        print(f"Enforced styles: {summary['input']} -> {summary['output']}")
        print(f"Updated paragraph/character style fonts: {summary.get('updated_style_fonts', 0)}")
        print(f"Updated paragraph styles: {summary['updated_paragraph_styles']}")
        print(f"Removed paragraph properties: {summary['removed_paragraph_properties']}")
        print(f"Removed run properties: {summary['removed_run_properties']}")
    finally:
        cleanup_temp(temp_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Enforce canonical DOCX styles and remove direct formatting")
    sub = parser.add_subparsers(dest="command", required=True)
    enforce = sub.add_parser("enforce")
    enforce.add_argument("input")
    enforce.add_argument("output")
    enforce.add_argument("--report-json")
    enforce.add_argument("--report-md")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "enforce":
        cmd_enforce(args)
        return 0
    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
