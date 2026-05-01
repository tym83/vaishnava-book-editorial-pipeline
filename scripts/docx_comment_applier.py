#!/usr/bin/env python3
# Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
# SPDX-License-Identifier: Apache-2.0

"""
Apply a review issue bundle as Word comments inside a DOCX file.

Examples:
  python3 docx_comment_applier.py apply input.docx issues.json output.docx
  python3 docx_comment_applier.py apply input.docx issues.json output.docx --author "Sluj editorial" --initials SL
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from lxml import etree

from review_issue_utils import ISSUE_BUNDLE_VERSION, issue_body, load_json


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"w": W_NS, "ct": CT_NS, "pr": REL_NS, "r": DOC_REL_NS}
W = f"{{{W_NS}}}"
CT = f"{{{CT_NS}}}"
PR = f"{{{REL_NS}}}"

COMMENTS_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
COMMENTS_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def convert_doc_to_docx(path: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="docx-comment-applier-"))
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


def resolve_docx(path: Path) -> Tuple[Path, Optional[Path]]:
    if not path.exists():
        die(f"Input file not found: {path}")
    if path.suffix.lower() == ".doc":
        converted = convert_doc_to_docx(path)
        return converted, converted.parent
    if path.suffix.lower() != ".docx":
        die("docx_comment_applier supports .docx and .doc only")
    return path, None


def cleanup_temp(temp_dir: Optional[Path]) -> None:
    if temp_dir and temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)


def xml_bytes(root) -> bytes:
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone="yes")


def load_xml(z: zipfile.ZipFile, name: str):
    return etree.fromstring(z.read(name))


def iter_story_parts(z: zipfile.ZipFile) -> Iterable[tuple[str, etree._Element]]:
    part_names = ["word/document.xml", "word/footnotes.xml", "word/endnotes.xml", "word/comments.xml"]
    for name in z.namelist():
        if name in part_names or ((name.startswith("word/header") or name.startswith("word/footer")) and name.endswith(".xml")):
            try:
                yield name, load_xml(z, name)
            except etree.XMLSyntaxError:
                continue


def iter_paragraphs_for_part(part_name: str, root) -> List[etree._Element]:
    if part_name == "word/document.xml":
        return root.xpath(".//w:body//w:p", namespaces=NS)
    if part_name == "word/footnotes.xml":
        return root.xpath(".//w:footnote[not(@w:type)]//w:p", namespaces=NS)
    if part_name == "word/endnotes.xml":
        return root.xpath(".//w:endnote[not(@w:type)]//w:p", namespaces=NS)
    return root.xpath(".//w:p", namespaces=NS)


def ensure_comments_part(parts: Dict[str, etree._Element], rels_root, content_types_root) -> etree._Element:
    comments_root = parts.get("word/comments.xml")
    if comments_root is None:
        comments_root = etree.Element(f"{W}comments", nsmap={"w": W_NS})
        parts["word/comments.xml"] = comments_root

    override_found = False
    for override in content_types_root.findall("ct:Override", namespaces=NS):
        if override.get("PartName") == "/word/comments.xml":
            override_found = True
            break
    if not override_found:
        etree.SubElement(
            content_types_root,
            f"{CT}Override",
            PartName="/word/comments.xml",
            ContentType=COMMENTS_CONTENT_TYPE,
        )

    rel_found = False
    max_rid = 0
    for rel in rels_root.findall("pr:Relationship", namespaces=NS):
        rid = rel.get("Id", "")
        if rid.startswith("rId"):
            try:
                max_rid = max(max_rid, int(rid[3:]))
            except ValueError:
                pass
        if rel.get("Type") == COMMENTS_REL_TYPE:
            rel_found = True
    if not rel_found:
        etree.SubElement(
            rels_root,
            f"{PR}Relationship",
            Id=f"rId{max_rid + 1}",
            Type=COMMENTS_REL_TYPE,
            Target="comments.xml",
        )

    return comments_root


def next_comment_id(comments_root) -> int:
    max_id = -1
    for comment in comments_root.findall("w:comment", namespaces=NS):
        raw = comment.get(f"{W}id")
        try:
            max_id = max(max_id, int(raw))
        except (TypeError, ValueError):
            continue
    return max_id + 1


def append_comment(comments_root, comment_id: int, body: str, author: str, initials: str) -> None:
    comment = etree.SubElement(
        comments_root,
        f"{W}comment",
        {
            f"{W}id": str(comment_id),
            f"{W}author": author,
            f"{W}initials": initials,
            f"{W}date": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        },
    )
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        p = etree.SubElement(comment, f"{W}p")
        r = etree.SubElement(p, f"{W}r")
        t = etree.SubElement(r, f"{W}t")
        if line.startswith(" ") or line.endswith(" "):
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = line or " "


def add_comment_markup(paragraph, comment_id: int) -> None:
    start = etree.Element(f"{W}commentRangeStart", {f"{W}id": str(comment_id)})
    end = etree.Element(f"{W}commentRangeEnd", {f"{W}id": str(comment_id)})
    ref_run = etree.Element(f"{W}r")
    rpr = etree.SubElement(ref_run, f"{W}rPr")
    etree.SubElement(rpr, f"{W}rStyle", {f"{W}val": "CommentReference"})
    etree.SubElement(ref_run, f"{W}commentReference", {f"{W}id": str(comment_id)})

    insert_at = 0
    first = paragraph[0] if len(paragraph) else None
    if first is not None and first.tag == f"{W}pPr":
        insert_at = 1
    paragraph.insert(insert_at, start)
    paragraph.append(end)
    paragraph.append(ref_run)


def apply_comments(
    input_path: Path,
    issues_path: Path,
    output_path: Path,
    author: str,
    initials: str,
    report_json: Optional[Path],
    report_md: Optional[Path],
) -> Dict[str, object]:
    bundle = load_json(issues_path)
    if bundle.get("version") != ISSUE_BUNDLE_VERSION:
        die(f"Unsupported issue bundle version: {bundle.get('version')}")

    src, temp_dir = resolve_docx(input_path)
    try:
        with zipfile.ZipFile(src, "r") as zin:
            parts = {name: root for name, root in iter_story_parts(zin)}
            if "word/document.xml" not in parts:
                die("word/document.xml not found")
            content_types_root = load_xml(zin, "[Content_Types].xml")
            rels_root = load_xml(zin, "word/_rels/document.xml.rels")
            comments_root = ensure_comments_part(parts, rels_root, content_types_root)

            applied: List[Dict[str, object]] = []
            skipped: List[Dict[str, object]] = []
            comment_id = next_comment_id(comments_root)

            for issue in bundle.get("issues", []):
                anchor = issue.get("anchor") or {}
                part_name = str(anchor.get("part") or "word/document.xml")
                paragraph_index = int(anchor.get("paragraph_index") or 1)
                root = parts.get(part_name)
                if root is None:
                    skipped.append({"id": issue.get("id"), "reason": f"part_not_found:{part_name}"})
                    continue
                paragraphs = iter_paragraphs_for_part(part_name, root)
                if paragraph_index < 1 or paragraph_index > len(paragraphs):
                    skipped.append(
                        {
                            "id": issue.get("id"),
                            "reason": f"paragraph_out_of_range:{part_name}#{paragraph_index}",
                        }
                    )
                    continue
                paragraph = paragraphs[paragraph_index - 1]
                append_comment(comments_root, comment_id, issue_body(issue), author, initials)
                add_comment_markup(paragraph, comment_id)
                applied.append(
                    {
                        "id": issue.get("id"),
                        "part": part_name,
                        "paragraph_index": paragraph_index,
                        "comment_id": comment_id,
                    }
                )
                comment_id += 1

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                for info in zin.infolist():
                    data = zin.read(info.filename)
                    if info.filename == "[Content_Types].xml":
                        data = xml_bytes(content_types_root)
                    elif info.filename == "word/_rels/document.xml.rels":
                        data = xml_bytes(rels_root)
                    elif info.filename in parts:
                        data = xml_bytes(parts[info.filename])
                    zout.writestr(info, data)
                if "word/comments.xml" not in zin.namelist():
                    zout.writestr("word/comments.xml", xml_bytes(parts["word/comments.xml"]))

        summary = {
            "input": str(input_path),
            "issues": str(issues_path),
            "output": str(output_path),
            "author": author,
            "initials": initials,
            "applied": applied,
            "skipped": skipped,
        }
        if report_json:
            report_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        if report_md:
            lines = [
                "# DOCX Comment Apply Report",
                "",
                f"Input: `{input_path}`",
                f"Issues: `{issues_path}`",
                f"Output: `{output_path}`",
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
                    lines.append(
                        f"- `{item['id']}` -> {item['part']}#{item['paragraph_index']} comment_id={item['comment_id']}"
                    )
            lines.extend(["", "## Skipped"])
            if not skipped:
                lines.append("- none")
            else:
                for item in skipped[:200]:
                    lines.append(f"- `{item['id']}` {item['reason']}")
            report_md.write_text("\n".join(lines), encoding="utf-8")
        return summary
    finally:
        cleanup_temp(temp_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply issue bundle as Word comments")
    sub = parser.add_subparsers(dest="command", required=True)

    apply_cmd = sub.add_parser("apply")
    apply_cmd.add_argument("input_docx")
    apply_cmd.add_argument("issues_json")
    apply_cmd.add_argument("output_docx")
    apply_cmd.add_argument("--author", default="Codex")
    apply_cmd.add_argument("--initials", default="CX")
    apply_cmd.add_argument("--report-json")
    apply_cmd.add_argument("--report-md")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "apply":
        parser.error("Unknown command")
        return 2
    summary = apply_comments(
        Path(args.input_docx),
        Path(args.issues_json),
        Path(args.output_docx),
        args.author,
        args.initials,
        Path(args.report_json) if args.report_json else None,
        Path(args.report_md) if args.report_md else None,
    )
    print(json.dumps({"applied": len(summary["applied"]), "skipped": len(summary["skipped"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
