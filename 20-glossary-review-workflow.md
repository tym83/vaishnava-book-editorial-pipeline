# Glossary Review Workflow v2

## 1. Вход

Черновой extraction уже собран:

- [glossary_base_draft.csv](/home/tym83/Загрузки/Служение/Automate/glossary/glossary_base_draft.csv)
- [glossary_seed_high_signal.csv](/home/tym83/Загрузки/Служение/Automate/glossary/glossary_seed_high_signal.csv)
- [glossary_conflicts.csv](/home/tym83/Загрузки/Служение/Automate/glossary/glossary_conflicts.csv)

В `v2` этот extraction уже:

- не включает шлоки и пословный перевод;
- не тащит `vedabase-only` кандидатов в рабочий словарь;
- опирается прежде всего на русские книги БВКС и ваши рабочие переводы.

---

## 2. Что редактировать руками

Основной рабочий файл:

- [glossary_review_master.csv](/home/tym83/Загрузки/Служение/Automate/glossary/review_pack/glossary_review_master.csv)

Дополнительно можно смотреть категории по отдельности:

- [by_category](/home/tym83/Загрузки/Служение/Automate/glossary/review_pack/by_category)

---

## 3. Какие колонки важны

Редактор заполняет:

- `decision`
- `approved_form_override`
- `category_override`
- `italic_required_override`
- `diacritics_policy_override`
- `merge_into`
- `review_notes`

Разрешенные решения в `decision`:

- `keep`
- `drop`
- `rename`
- `merge`
- `reclassify`
- `defer`

---

## 4. Как интерпретировать решения

### `keep`

Оставить запись как есть.

### `drop`

Убрать как шум / ложное срабатывание.

### `rename`

Оставить запись, но заменить `approved_form` через `approved_form_override`.

### `merge`

Объединить с другой записью.  
В `merge_into` указать целевую форму.

### `reclassify`

Исправить категорию через `category_override`.

### `defer`

Пока оставить без решения.

---

## 5. Что запускать после ручной правки

Сборщик:

- [glossary_apply_review.py](/home/tym83/Загрузки/Служение/Automate/scripts/glossary_apply_review.py)

Он создает:

- `glossary_approved.csv`
- `glossary_dropped.csv`
- `glossary_pending_review.csv`
- `glossary_aliases.csv`

---

## 6. Общий цикл

1. Пройти `glossary_review_master.csv`.
2. Заполнить решения.
3. Прогнать `glossary_apply_review.py`.
4. Получить `approved glossary`.
5. При необходимости повторить цикл.
