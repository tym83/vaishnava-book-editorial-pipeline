# Next Steps

This file is the practical continuation backlog for the next Codex session.

## First Start On A New PC

1. Read:
   - [AGENTS.md](./AGENTS.md)
   - [PROJECT_STATUS.md](./PROJECT_STATUS.md)
   - [README.md](./README.md)
   - [docs/README.md](./docs/README.md)
2. Make sure the external corpora you need are also present or remapped:
   - local `Vedabase` mirror
   - BBT correction docs
   - BVKS Russian books
3. Create a Python environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

4. Run a quick smoke check:

```bash
python3 -m py_compile $(find scripts -name '*.py')
python3 scripts/editorial_pipeline.py --help
python3 scripts/stylistic_reviewer.py --help
python3 scripts/docx_style_audit.py --help
```

## Immediate Recommended Work

The most productive next step is not more speculative architecture work.

Do this next:

1. Run glossary-aware review on one real BVKS book.
2. Inspect the noise and missing terminology.
3. Expand the manual glossary only from real evidence.
4. Then run the full editorial pipeline on the same book.

## Recommended Commands

Glossary-aware stylistic review on numbered chapters:

```bash
python3 scripts/stylistic_reviewer.py review-dir \
  /path/to/target_chapters \
  /path/to/output/stylistic_review \
  --glossary-approved glossary/manual_bbt_v1/glossary_approved.csv \
  --write-bundles
```

Style audit on one `DOCX`:

```bash
python3 scripts/docx_style_audit.py audit \
  /path/to/book.docx \
  --glossary-approved glossary/manual_bbt_v1/glossary_approved.csv \
  --report-json /path/to/style_audit.json \
  --report-md /path/to/style_audit.md
```

Chapter-level editorial pipeline:

```bash
python3 scripts/editorial_pipeline.py run-dir \
  /path/to/source_chapters \
  /path/to/target_chapters \
  /path/to/output/editorial_run \
  --reference-root /path/to/vedabase \
  --glossary-approved glossary/manual_bbt_v1/glossary_approved.csv \
  --normalize-unicode \
  --normalize-styles \
  --normalize-scripture-refs \
  --apply-comments
```

Whole-book pipeline:

```bash
python3 scripts/editorial_pipeline.py run-book \
  /path/to/source_book.docx \
  /path/to/target_book.docx \
  /path/to/output/book_run \
  --split-mode style \
  --reference-root /path/to/vedabase \
  --glossary-approved glossary/manual_bbt_v1/glossary_approved.csv \
  --normalize-unicode \
  --normalize-styles \
  --normalize-scripture-refs \
  --apply-comments
```

## Priority Backlog

### 1. Real-Book Calibration

- Run one real book through `stylistic_reviewer`, `docx_style_audit`, and `editorial_pipeline`.
- Record false positives.
- Record missing glossary terms.
- Tighten only the rules that fail on real text.

### 2. Glossary Expansion

The glossary should now grow from evidence, not from broad auto-extraction.

Preferred loop:

1. run on real book
2. collect missing terms and unstable forms
3. verify against BBT docs
4. verify against approved Russian usage
5. enrich from BVKS / `Vedabase` RU
6. update manual glossary and rule docs together

### 3. Update-Helper Validation

- Run [scripts/old_ru_vs_new_en_update_helper.py](./scripts/old_ru_vs_new_en_update_helper.py) on a real `old EN + new EN + old RU` set.
- Check whether its queue is useful or too noisy.
- Adjust severity and heuristics only after one real book pass.

### 4. InDesign Validation

- On a machine with InDesign, validate:
  - [scripts/word_to_indesign_import.jsx](./scripts/word_to_indesign_import.jsx)
  - [scripts/indesign_layout_qa.jsx](./scripts/indesign_layout_qa.jsx)
- Do one real `Word -> InDesign -> QA` pass and record gaps.

## Documentation Discipline

If you change behavior, update docs in the same session.

Minimum sync set:

- [PROJECT_STATUS.md](./PROJECT_STATUS.md)
- [NEXT_STEPS.md](./NEXT_STEPS.md)
- [10-script-specs.md](./10-script-specs.md)

If the change is glossary-related, also update:

- [glossary/manual_bbt_v1/glossary_approved.csv](./glossary/manual_bbt_v1/glossary_approved.csv)
- [glossary/manual_bbt_v1/BBT_STYLE_RULES.md](./glossary/manual_bbt_v1/BBT_STYLE_RULES.md)
- [glossary/manual_bbt_v1/README.md](./glossary/manual_bbt_v1/README.md)
- [glossary/README.md](./glossary/README.md)
- [05-style-guide.md](./05-style-guide.md)
- [09-glossary-spec.md](./09-glossary-spec.md)
- [20-glossary-review-workflow.md](./20-glossary-review-workflow.md)
