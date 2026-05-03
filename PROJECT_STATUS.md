# Project Status

Snapshot date: `2026-05-03`

## Repository State

The repository is a working `v1` toolkit with active local changes.

What is already in place:

- chapter splitting
- structural normalization
- `EN -> RU` completeness comparison
- `Vedabase` reference lookup and scripture-reference cleanup
- deterministic semantic and stylistic review queues
- style audit and comment application
- `Word -> InDesign` import support and layout QA helpers

## Current High-Confidence Modules

Core deterministic modules already exist and are usable:

- [scripts/chapter_splitter.py](./scripts/chapter_splitter.py)
- [scripts/structure_normalizer.py](./scripts/structure_normalizer.py)
- [scripts/source_ru_comparator.py](./scripts/source_ru_comparator.py)
- [scripts/vedabase_reference_resolver.py](./scripts/vedabase_reference_resolver.py)
- [scripts/docx_scripture_reference_pipeline.py](./scripts/docx_scripture_reference_pipeline.py)
- [scripts/semantic_reviewer.py](./scripts/semantic_reviewer.py)
- [scripts/stylistic_reviewer.py](./scripts/stylistic_reviewer.py)
- [scripts/docx_style_audit.py](./scripts/docx_style_audit.py)
- [scripts/editorial_pipeline.py](./scripts/editorial_pipeline.py)
- [scripts/docx_comment_applier.py](./scripts/docx_comment_applier.py)
- [scripts/word_to_indesign_import.jsx](./scripts/word_to_indesign_import.jsx)
- [scripts/indesign_layout_qa.jsx](./scripts/indesign_layout_qa.jsx)

## Major Recent Changes

The latest working layer is glossary-centered.

What changed recently:

- the project switched from auto-extracted glossary packs to a manual BBT-backed canonical glossary base
- the canonical glossary is now:
  - [glossary/manual_bbt_v1/glossary_approved.csv](./glossary/manual_bbt_v1/glossary_approved.csv)
- the supporting rule docs are:
  - [glossary/manual_bbt_v1/BBT_STYLE_RULES.md](./glossary/manual_bbt_v1/BBT_STYLE_RULES.md)
  - [glossary/manual_bbt_v1/README.md](./glossary/manual_bbt_v1/README.md)
- a shared loader was added:
  - [scripts/glossary_policy.py](./scripts/glossary_policy.py)
- glossary policy is now wired into:
  - [scripts/semantic_reviewer.py](./scripts/semantic_reviewer.py)
  - [scripts/stylistic_reviewer.py](./scripts/stylistic_reviewer.py)
  - [scripts/docx_style_audit.py](./scripts/docx_style_audit.py)
  - [scripts/editorial_pipeline.py](./scripts/editorial_pipeline.py)

## Glossary Snapshot

Current manual glossary snapshot:

- approved entries: `85`
- canonical pipeline status file:
  - [glossary/README.md](./glossary/README.md)

Completed manual batches:

- base manual `v1`
- `Batch 2A`: core terms and compounds
- `Batch 2B`: title forms and direct/italic fixed compounds
- `Batch 2C`: geographic forms and `-дхама` place names

Current local house overrides:

- `Гурудев`
- `Гуру Махарадж`

## Still Not Fully Hardened

The following areas remain intentionally non-final:

- real end-to-end run on a full production book still needs calibration
- semantic reviewer is deterministic and useful, but not a full meaning/theology judge
- stylistic reviewer is strong on surface issues and glossary policy, but not a literary editor
- `old RU vs new EN` helper exists, but still needs more real-book validation
- `Word -> InDesign -> layout QA` still needs routine validation on a machine with InDesign

## Main Open Risks

- glossary coverage is much stronger, but still incomplete
- conditional italic/capitalization cases still require human review
- corpus-driven false positives and missed forms will only surface through real-book runs
- many external corpora used during development are not stored inside this repo

## External Inputs Expected During Real Work

This repo does not include all working corpora.

For the original working environment, the project relied on:

- BBT correction docs outside the repo
- BVKS Russian working/reference books outside the repo
- local `Vedabase` mirror outside the repo

If the repo is copied to another PC without those assets, code/docs work can continue, but glossary expansion and reference-backed review will be partially blocked.

## Recommended Reading Order On A New Machine

1. [AGENTS.md](./AGENTS.md)
2. [README.md](./README.md)
3. [PROJECT_STATUS.md](./PROJECT_STATUS.md)
4. [NEXT_STEPS.md](./NEXT_STEPS.md)
5. [docs/README.md](./docs/README.md)

Then move into:

- [04-master-workflow.md](./04-master-workflow.md)
- [05-style-guide.md](./05-style-guide.md)
- [10-script-specs.md](./10-script-specs.md)
- [21-review-annotation-workflow.md](./21-review-annotation-workflow.md)
