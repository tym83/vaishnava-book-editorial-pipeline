# Session Handoff

Snapshot date: `2026-05-03`

Use this file when you need the shortest possible restart context on a new machine.

## Where The Project Is

- The repository is a working `v1` of the Vaishnava book editorial pipeline.
- The project already has working deterministic modules for:
  - chapter splitting
  - structural normalization
  - source-vs-target comparison
  - `Vedabase` reference lookup
  - scripture-reference cleanup
  - semantic/stylistic review queues
  - style audit
  - Word comment application
  - `Word -> InDesign` support scripts
- `Vedabase` is a reference layer only. It is not the primary translation source.

## Current Canonical Glossary State

- Canonical glossary:
  - [glossary/manual_bbt_v1/glossary_approved.csv](./glossary/manual_bbt_v1/glossary_approved.csv)
- Supporting rule docs:
  - [glossary/manual_bbt_v1/BBT_STYLE_RULES.md](./glossary/manual_bbt_v1/BBT_STYLE_RULES.md)
  - [glossary/manual_bbt_v1/README.md](./glossary/manual_bbt_v1/README.md)
- Current snapshot: `85` approved entries.
- House style decisions currently fixed:
  - `Гурудев`
  - `Гуру Махарадж`

## What To Read First

1. [AGENTS.md](./AGENTS.md)
2. [PROJECT_STATUS.md](./PROJECT_STATUS.md)
3. [NEXT_STEPS.md](./NEXT_STEPS.md)
4. [README.md](./README.md)
5. [docs/README.md](./docs/README.md)

## What To Do First

1. Restore or remap the external corpora you need:
   - BBT correction docs
   - BVKS Russian books
   - local `Vedabase` mirror if reference checks are needed
2. Create a virtual environment and install dependencies.
3. Run smoke checks on the main CLIs.
4. Pick one real BVKS book and run:
   - `stylistic_reviewer`
   - `docx_style_audit`
   - `editorial_pipeline`
5. Expand the glossary only from real evidence found in that run.

## External Assets

This repository does not contain every working corpus by itself.

For practical continuation on another PC, carry over:

- repo itself
- BBT correction docs
- BVKS Russian books/corpora

Do not carry over `Vedabase` only if you intentionally want a lighter package and can remap it later.

## Current Main Risk

The biggest remaining gap is not architecture. It is calibration on real books:

- glossary still needs expansion from real usage
- semantic reviewer is useful but deterministic
- stylistic reviewer is not a literary editor
- full production book runs still need routine validation
