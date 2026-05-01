# Glossary Review Pack

- total rows: 44

## Suggested actions
- `review`: 22
- `keep`: 22

## Review priority
- `high`: 22
- `medium`: 22

## Categories
- `philosophical_term`: 26
- `personal_name`: 6
- `place_name`: 6
- `honorific`: 5
- `scripture_title`: 1

## How to use
1. Start with `glossary_review_master.csv`.
2. Fill `decision` for each row: `keep`, `drop`, `rename`, `merge`, `reclassify`, `defer`.
3. Use override columns only when the current auto-choice is wrong.
4. If `decision=merge`, fill `merge_into` with the target approved form.
5. If `decision=rename`, fill `approved_form_override`.
6. Then run `glossary_apply_review.py`.
