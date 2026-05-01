# Glossary Review Pack

- total rows: 919

## Suggested actions
- `keep`: 535
- `review`: 370
- `drop`: 14

## Review priority
- `medium`: 618
- `low`: 211
- `high`: 90

## Categories
- `other`: 307
- `philosophical_term`: 212
- `place_name`: 167
- `personal_name`: 86
- `honorific`: 85
- `scripture_title`: 62

## How to use
1. Start with `glossary_review_master.csv`.
2. Fill `decision` for each row: `keep`, `drop`, `rename`, `merge`, `reclassify`, `defer`.
3. Use override columns only when the current auto-choice is wrong.
4. If `decision=merge`, fill `merge_into` with the target approved form.
5. If `decision=rename`, fill `approved_form_override`.
6. Then run `glossary_apply_review.py`.
