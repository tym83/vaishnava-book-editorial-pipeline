# Vaishnava Book Editorial Pipeline

Automation toolkit and workflow documentation for translating, reviewing, proofreading, and typesetting Vaishnava books in a chapter-based pipeline.

This repository is focused on the deterministic parts of the workflow:

- chapter splitting;
- structural normalization;
- `EN -> RU` completeness checks;
- `Vedabase` reference lookup and scripture-reference cleanup;
- semantic and stylistic review queues;
- Word comment application;
- `Word -> InDesign` import support and layout QA.

It is not a single "translation bot". It is an editorial pipeline around `DOCX`, review artifacts, and `InDesign`.

## Status

Current state: `v1` working toolkit.

What already exists:

- reusable CLI scripts in [scripts](./scripts);
- long-form workflow and spec documents in the repository root;
- glossary and hint artifacts in [glossary](./glossary) and [hints](./hints);
- review-issue schema and appliers for `docx`, `pdf`, and `indd`.

What is still intentionally human-controlled:

- final translation decisions;
- theological judgment;
- literary Russian editing;
- disputed terminology decisions.

## Core Workflow

High-level editorial flow:

1. Normalize source and target structure.
2. Split books into chapter files.
3. Run completeness comparison.
4. Run semantic review queue.
5. Run stylistic/proofreading queue.
6. Run style and footnote checks.
7. Merge issues into a single review bundle.
8. Apply comments to `DOCX` or annotations to `PDF` / notes to `InDesign`.
9. Import into `InDesign` and run layout QA.

The canonical long-form workflow is in [04-master-workflow.md](./04-master-workflow.md).

## Repository Layout

```text
.
├── scripts/          CLI tools and InDesign JSX automation
├── docs/             GitHub-friendly navigation and curated repo docs
├── glossary/         glossary sources and review artifacts
├── hints/            manual training/review hints for heuristic classifiers
├── review_issues/    issue schema templates
├── 01-21 *.md        original planning, workflow, and spec documents
└── requirements.txt  Python dependencies for the CLI layer
```

## Key Entry Points

Main CLI tools:

- [chapter_splitter.py](./scripts/chapter_splitter.py)
- [structure_normalizer.py](./scripts/structure_normalizer.py)
- [source_ru_comparator.py](./scripts/source_ru_comparator.py)
- [semantic_reviewer.py](./scripts/semantic_reviewer.py)
- [stylistic_reviewer.py](./scripts/stylistic_reviewer.py)
- [old_ru_vs_new_en_update_helper.py](./scripts/old_ru_vs_new_en_update_helper.py)
- [editorial_pipeline.py](./scripts/editorial_pipeline.py)
- [docx_comment_applier.py](./scripts/docx_comment_applier.py)
- [word_to_indesign_import.jsx](./scripts/word_to_indesign_import.jsx)
- [indesign_layout_qa.jsx](./scripts/indesign_layout_qa.jsx)

## Requirements

Python:

- `Python 3.11+`
- packages from [requirements.txt](./requirements.txt)

System tools used by different scripts:

- `LibreOffice` / `soffice`
- `pdftotext`
- `pdfinfo`
- `ghostscript`

Optional desktop dependency:

- `Adobe InDesign 2022+` for `.jsx` import and layout QA scripts

## Quick Start

Install Python dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Example commands:

Normalize a file into machine-readable JSON:

```bash
python3 scripts/structure_normalizer.py normalize input.docx output.json
```

Compare source vs target chapter:

```bash
python3 scripts/source_ru_comparator.py compare source.docx target.docx \
  --report-json compare.json \
  --report-md compare.md
```

Run the chapter-level editorial pipeline:

```bash
python3 scripts/editorial_pipeline.py run-dir source_chapters target_chapters output_dir \
  --reference-root /path/to/vedabase \
  --apply-comments
```

## Documentation

Start here:

- [docs/README.md](./docs/README.md)
- [docs/GETTING_STARTED.md](./docs/GETTING_STARTED.md)
- [docs/REPOSITORY_STRUCTURE.md](./docs/REPOSITORY_STRUCTURE.md)
- [docs/SCRIPT_CATALOG.md](./docs/SCRIPT_CATALOG.md)
- [docs/GITHUB_REPOSITORY_SETUP.md](./docs/GITHUB_REPOSITORY_SETUP.md)

Canonical design and spec documents:

- [04-master-workflow.md](./04-master-workflow.md)
- [05-style-guide.md](./05-style-guide.md)
- [08-qa-checklists.md](./08-qa-checklists.md)
- [10-script-specs.md](./10-script-specs.md)
- [21-review-annotation-workflow.md](./21-review-annotation-workflow.md)

## License

This repository is licensed under `Apache-2.0`.

- Full license text: [LICENSE](./LICENSE)
- Source files in [scripts](./scripts) carry `SPDX-License-Identifier: Apache-2.0` headers

## Notes

- The repository currently keeps the original numbered design documents in the root for traceability.
- `Vedabase` is used as a reference layer, not as the authoritative translation source.
- The preferred unit of work is a chapter, not a whole book.
