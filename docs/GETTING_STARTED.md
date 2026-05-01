# Getting Started

## Environment

Recommended baseline:

- `Python 3.11+`
- Linux/macOS shell environment for CLI runs
- `LibreOffice` for `.doc -> .docx` conversion
- `Poppler` tools:
  - `pdftotext`
  - `pdfinfo`
- `Ghostscript` for PDF annotations
- `Adobe InDesign 2022+` for `.jsx` import and layout QA

## Python Dependencies

Install:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Main Directories

- [../scripts](../scripts) — CLI tools and InDesign JSX scripts
- [../glossary](../glossary) — glossary sources and review artifacts
- [../hints](../hints) — manual hints for heuristic classifiers
- [../review_issues](../review_issues) — issue bundle templates

## First Useful Commands

Normalize a file:

```bash
python3 scripts/structure_normalizer.py normalize input.docx output.json
```

Compare source and target:

```bash
python3 scripts/source_ru_comparator.py compare source.docx target.docx \
  --report-json compare.json \
  --report-md compare.md
```

Resolve scripture references against local `Vedabase`:

```bash
python3 scripts/vedabase_reference_resolver.py scan chapter.docx \
  --vedabase-root /path/to/vedabase \
  --report-json refs.json \
  --report-md refs.md
```

Run the editorial pipeline on chapter directories:

```bash
python3 scripts/editorial_pipeline.py run-dir source_chapters target_chapters output_dir \
  --reference-root /path/to/vedabase \
  --apply-comments
```

## Suggested Validation

For Python changes:

```bash
python3 -m py_compile scripts/*.py
```

For a new or changed script, also run at least one smoke-test command against a real file or chapter pair.

## Practical Boundaries

- Work by chapter, not by whole book, unless the command is only doing splitting or indexing.
- Treat `Vedabase` as a reference layer.
- Keep high-stakes semantic and theological decisions visible as review issues, not silent rewrites.

