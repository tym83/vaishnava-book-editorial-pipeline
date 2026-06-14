# Repo Agent Notes

Use this file as the first repo-local handoff when opening the project on a new machine.

## Read First

1. [SESSION_HANDOFF.md](./SESSION_HANDOFF.md)
2. [README.md](./README.md)
3. [PROJECT_STATUS.md](./PROJECT_STATUS.md)
4. [NEXT_STEPS.md](./NEXT_STEPS.md)
5. [docs/README.md](./docs/README.md)

## Canonical Documents

Use these as the authoritative workflow/spec layer:

- [04-master-workflow.md](./04-master-workflow.md)
- [05-style-guide.md](./05-style-guide.md)
- [10-script-specs.md](./10-script-specs.md)
- [21-review-annotation-workflow.md](./21-review-annotation-workflow.md)

## Canonical Operational Rules

- This is not a translation bot. It is an editorial pipeline around `DOCX`, review artifacts, and `InDesign`.
- The preferred unit of work is a chapter, not a whole book.
- `Vedabase` is a reference layer, not the authoritative translation source.
- The canonical glossary source is:
  - [glossary/manual_bbt_v1/glossary_approved.csv](./glossary/manual_bbt_v1/glossary_approved.csv)
- Reference dictionaries derived from the BBT editorial codex and gold books
  (italic/names/geography/literature/words + rule digests) live in:
  - [glossary/bbt_codex_v1/](./glossary/bbt_codex_v1/) — consult for italic,
    capitalization, names, place names, titles, discouraged forms, and stylistics.
- Older glossary extraction artifacts are archival and non-canonical:
  - `glossary/review_pack*`
  - `glossary/glossary_base_draft.csv`
  - `glossary/glossary_seed_high_signal.csv`
  - `glossary/glossary_conflicts.csv`

## Current House Style Decisions

- Use `Гурудев`.
- Use `Гуру Махарадж`.
- The current manual glossary snapshot contains `121` approved entries as of `2026-06-14` (85 manual + 36 italic lemmas confirmed from gold books; 21 existing lemmas gained observed inflected forms).
- Italic terms confirmed by the proofread gold books are recorded in [glossary/bbt_codex_v1/book_italic.csv](./glossary/bbt_codex_v1/book_italic.csv); the codex italic rule is digested in [glossary/bbt_codex_v1/italic_rules.md](./glossary/bbt_codex_v1/italic_rules.md).
- `italic_required` glossary terms are italicized with the `Char Курсив` character style; when a term is inside a hyphenated compound the whole compound is italicized, including a sampradaya-name element (e.g. `рамануджа-садху`) — it marks belonging to a tradition, not the named person (Decision 013).
- Inline shloka citations embedded in prose are set in `Char Курсив` (transliteration = italic). Standalone poem lines get the `Шлока` paragraph style; their translations get `Основной текст` (Decision 015).
- OCR fixes are never blind find/replace: detect with corpus-internal evidence, apply only a human-reviewed correction map (Decision 014).

## Current Glossary Workflow

- Source order:
  1. BBT rule docs
  2. approved Russian house usage
  3. BVKS Russian corpus
  4. local `Vedabase` RU mirror
- If you change glossary policy, update the glossary data and the rule docs together:
  - [glossary/manual_bbt_v1/glossary_approved.csv](./glossary/manual_bbt_v1/glossary_approved.csv)
  - [glossary/manual_bbt_v1/BBT_STYLE_RULES.md](./glossary/manual_bbt_v1/BBT_STYLE_RULES.md)
  - [glossary/manual_bbt_v1/README.md](./glossary/manual_bbt_v1/README.md)
  - [05-style-guide.md](./05-style-guide.md)
  - [09-glossary-spec.md](./09-glossary-spec.md)
  - [20-glossary-review-workflow.md](./20-glossary-review-workflow.md)
  - [10-script-specs.md](./10-script-specs.md)
  - [glossary/bbt_codex_v1/](./glossary/bbt_codex_v1/) — the BBT-codex reference
    dictionaries and rule digests (keep in sync when codex policy changes).

## Current Script Integration

Glossary-backed behavior currently lives in:

- [scripts/glossary_policy.py](./scripts/glossary_policy.py)
- [scripts/semantic_reviewer.py](./scripts/semantic_reviewer.py)
- [scripts/stylistic_reviewer.py](./scripts/stylistic_reviewer.py)
- [scripts/docx_style_audit.py](./scripts/docx_style_audit.py)
- [scripts/editorial_pipeline.py](./scripts/editorial_pipeline.py)

Stage `-1` style-finishing helpers (apply on a `*.formatted.docx`, keep a backup, re-run `docx_style_audit.py`):

- [scripts/docx_glossary_italicizer.py](./scripts/docx_glossary_italicizer.py) — glossary terms / compounds → `Char Курсив`.
- [scripts/docx_ocr_corrector.py](./scripts/docx_ocr_corrector.py) — `detect` (corpus-internal, needs `spylls`) then `apply` a reviewed correction map.
- [scripts/docx_inline_verse_styler.py](./scripts/docx_inline_verse_styler.py) — poems → `Шлока`, translations → `Основной текст`, inline shlokas → `Char Курсив`, from a reviewed plan.

Gold-corpus italic seeding:

- [scripts/extract_book_italic.py](./scripts/extract_book_italic.py) — extract italic spans from proofread `.docx`/`.pdf` books (run/`Char Курсив` style for DOCX, font flags for PDF) into frequency-ranked candidates; source of [glossary/bbt_codex_v1/book_italic.csv](./glossary/bbt_codex_v1/book_italic.csv).

## External Assets

The full BBT editorial codex (the raw `.doc` correction docs + converted text)
now lives **in-project** under
[`glossary/bbt_codex_v1/_codex_source/`](./glossary/bbt_codex_v1/_codex_source/),
which is **git-ignored** (third-party material, public repo) but present locally,
so editorial work no longer depends on the external USB codex folder. The
committed, shareable layer is the derived dictionaries and rule digests in
`glossary/bbt_codex_v1/`.

Still external by nature (large / copyrighted, not bundled):

- local `Vedabase` mirror (reference layer)
- BVKS Russian working/reference books
- the gold source books used by `extract_book_italic.py` (their derived
  `book_italic.csv` is committed; the books themselves are needed only to
  re-run extraction). On the original machine these lived under `~/Загрузки/...`.

## What Not To Do

- Do not treat `Vedabase` as the primary translation source.
- Do not resurrect auto-generated glossary review packs as the canonical glossary.
- Do not automate conditional italic/capitalization cases without corpus evidence and an explicit rule update.
- Do not assume semantic/stylistic reviewers replace human theological or literary judgment.
