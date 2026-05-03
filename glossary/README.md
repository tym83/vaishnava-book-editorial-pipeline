# Glossary Status

## Current Canonical Source

Use:

- [manual_bbt_v1/glossary_approved.csv](/home/tym83/Загрузки/Служение/Automate/glossary/manual_bbt_v1/glossary_approved.csv)

Read alongside:

- [manual_bbt_v1/README.md](/home/tym83/Загрузки/Служение/Automate/glossary/manual_bbt_v1/README.md)
- [manual_bbt_v1/BBT_STYLE_RULES.md](/home/tym83/Загрузки/Служение/Automate/glossary/manual_bbt_v1/BBT_STYLE_RULES.md)

## What Changed

The glossary is no longer treated as:

- `auto extraction -> review pack -> eventually approved`

for the main editorial base.

The current approach is:

- `BBT rule docs -> manual curation -> BVKS corpus check -> Vedabase RU enrichment`

## Status Of Older Files

These remain useful, but they are not canonical anymore:

- [review_pack_v2/glossary_review_master.csv](/home/tym83/Загрузки/Служение/Automate/glossary/review_pack_v2/glossary_review_master.csv)
- [review_pack/glossary_review_master.csv](/home/tym83/Загрузки/Служение/Automate/glossary/review_pack/glossary_review_master.csv)
- [glossary_base_draft.csv](/home/tym83/Загрузки/Служение/Automate/glossary/glossary_base_draft.csv)
- [glossary_seed_high_signal.csv](/home/tym83/Загрузки/Служение/Automate/glossary/glossary_seed_high_signal.csv)
- [glossary_conflicts.csv](/home/tym83/Загрузки/Служение/Automate/glossary/glossary_conflicts.csv)

Treat them as:

- extraction artifacts;
- candidate inventories;
- auxiliary research material.

## Practical Use

The manual glossary now feeds:

- `semantic_reviewer.py` through multi-form `lemma_en`;
- `stylistic_reviewer.py` through `discouraged_forms`;
- `docx_style_audit.py` through `italic_automation=always|never`;
- `editorial_pipeline.py` through `--glossary-approved`.

## Current Limits

- not all corpus terms are covered yet;
- many conditional italic/capitalization cases still require human review;
- `manual_bbt_v1` is a strong base, not the final closed glossary of the whole project.
