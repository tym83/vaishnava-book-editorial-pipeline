# Glossary Candidate Extractor Spec v2

## 1. Скрипт

- [glossary_candidate_extractor.py](/home/tym83/Загрузки/Служение/Automate/scripts/glossary_candidate_extractor.py)

Среда:

- `Python 3`
- без внешних Python-зависимостей
- fallback tools:
  - `pdftotext`
  - `soffice` для части legacy `.doc`

---

## 2. Что делает v2

Скрипт собирает черновую терминологическую базу из:

- локального `vedabase` в HTML;
- `docx`;
- части `doc` через `soffice`;
- `pdf` как fallback без курсивной информации.

На выходе пишет:

- `glossary_base_draft.csv`
- `glossary_seed_high_signal.csv`
- `glossary_conflicts.csv`
- `glossary_extraction_summary.md`

---

## 3. Логика v2

Extractor теперь сознательно консервативен. Он не пытается собрать все возможные слова из корпуса.

Он строит:

1. сырой normalized pool;
2. рабочий `draft/seed`, уже очищенный от большей части шума;
3. conflict-report для ручного решения.

Основные источники кандидатов:

- курсивные фрагменты из прозы;
- ограниченный набор glossary-like headwords;
- термины, имена, названия и honorifics, которые удается выделить эвристически из прозы.

Что extractor теперь **не берет**:

- шлоки;
- деванагари / бенгали;
- пословный перевод / synonyms;
- inline-транслитерацию шлок как отдельные блоки;
- footnotes/endnotes из `docx`;
- `vedabase-only` кандидатов без подтверждения в русских книгах БВКС / ваших рабочих переводах.

Для `vedabase` extractor берет только:

- литературный перевод;
- purport / commentary.

`vedabase` используется как supporting corpus, а не как основной генератор кандидатов.

---

## 4. Что считать главным результатом

Для редакторской работы основным выходом `v1` считается:

- [glossary_seed_high_signal.csv](/home/tym83/Загрузки/Служение/Automate/glossary/glossary_seed_high_signal.csv)

А не полный `glossary_base_draft.csv`.

Почему:

- raw pool intentionally широкий;
- в `seed` шум уже существенно срезан;
- seed лучше подходит как стартовая база для ручного утверждения.

---

## 5. Ограничения v2

1. В `vedabase` extractor берет только translation/purport/commentary, но структура HTML все равно читается эвристически.
2. Legacy-русские документы могут давать смешанный или шумный материал.
3. `doc`-конвертация через `soffice` нестабильна и может не сработать для части файлов.
4. Категоризация (`personal_name`, `place_name`, `scripture_title`, etc.) пока эвристическая.
5. `approved_form` в `v2` все еще auto-choice, хотя уже лучше сводит часть словоформ к лемме; это не редакторское утверждение.
6. Часть падежных форм и составных терминов все еще нужно вручную сводить на review-этапе.

---

## 6. Практический workflow

1. Прогнать extractor.
2. Смотреть сначала:
   - `glossary_seed_high_signal.csv`
   - `glossary_conflicts.csv`
3. Утверждать формы вручную.
4. По итогам собрать уже настоящий рабочий `approved glossary`.

---

## 7. Что делать дальше

Следующий разумный шаг после `v1`:

1. вручную просмотреть `high-signal seed`;
2. пометить:
   - верные формы;
   - неверные формы;
   - объединяемые варианты;
   - ложные срабатывания;
3. на основе этого добавить:
   - blacklist / stop rules;
   - alias rules;
   - category corrections;
   - approved forms.
