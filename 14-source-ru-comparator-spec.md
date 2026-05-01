# Source RU Comparator Spec v1

## 1. Назначение

Скрипт нужен для структурной проверки полноты перевода между source chapter и RU chapter.

Он не делает семантический bilingual review.  
Его задача:

- находить пропуски и лишние блоки;
- находить поломку структуры;
- находить несходство по шлокам, спискам, заголовкам, ссылочным якорям и сноскам;
- готовить основу для следующего AI-прохода `Completeness Reviewer`.

Скрипт:

- [source_ru_comparator.py](/home/tym83/Загрузки/Служение/Automate/scripts/source_ru_comparator.py)

---

## 2. Рабочая зона

Лучший режим:

- `DOCX/DOCX`
- на уровне одной главы
- после `chapter-splitter`
- желательно после `unicode-normalizer` и `docx_style_normalizer`

Новый поддерживаемый промежуточный режим:

- `normalized JSON` -> `DOCX`
- особенно для случаев, когда source уже нормализован структурно, даже если он не пришел из Word
- при необходимости можно подать и chapter-level JSON, собранный через `vedabase_chapter_assembler.py`

Допустимый, но менее надежный режим:

- `PDF -> DOCX`
- `PDF -> PDF/text`

Причина:

- `pdftotext` ломает абзацную структуру;
- whole-book PDF дает много структурного шума;
- сравнение по PDF годится как fallback, но не как главный контур.
- `normalized JSON` полезен как стабильный machine-readable слой между источником и review-скриптами.
- chapter-level JSON полезен тем, что сохраняет anchors:
  - `verse_id`
  - `source_locator`
  - chapter metadata
- `vedabase` при этом используется не как главный source перевода, а как optional reference layer.

---

## 3. Что сравнивается

Для каждого блока учитываются:

- порядковый индекс;
- style/kind;
- длина;
- количество ссылок на сноски;
- цифровая сигнатура;
- наличие цитатных маркеров;
- transliteration score.

Далее сравниваются:

- sequence of block signatures;
- counts by kind;
- total footnote reference counts;
- suspicious aligned pairs;
- insert/replace/delete segments.

---

## 4. Что он умеет

### `compare`

Сравнить одну source-главу и одну RU-главу.

Дополнительно может делать optional scripture-reference spot-check:

- `--reference-root /path/to/vedabase`
- проверка ссылок в target-файле на `BG/SB/CC/ISO`
- resolved / unresolved summary в JSON и Markdown report
- для каждой найденной ссылки:
  - `resolved`
  - `unresolved`
  - `needs_normalization`
  - `canonical_display`
  - `replacement_text`
- этот `target_reference_scan` потом можно напрямую передать в `review_issue_bundle.py`:
  - либо через `from-comparator`
  - либо отдельно через `from-reference-scan`

Выход:

- `json`
- `md`

### `compare-dir`

Сравнить две директории с главами по трехзначному префиксу:

- `001`
- `002`
- ...

Выход:

- пофайловые отчеты;
- `index.json`
- `index.md`

---

## 5. Что считать полезным сигналом

### Structural issues

- `struct_insert`
- `struct_delete`
- `struct_replace`

Это кандидаты на:

- missing fragment;
- extra fragment;
- поломанную сегментацию;
- пропавший/лишний служебный блок.

### Suspicious aligned blocks

Это блоки, где:

- не совпал kind;
- не совпали footnote refs;
- не совпала цифровая сигнатура.

Это не автоматический verdict, а материал для review.

---

## 6. Ограничения v1

1. Скрипт не понимает перевод по смыслу.
2. Он не может сам решить, что русский абзац правильно передает английский.
3. При повторяющихся `body`-абзацах выравнивание может быть приблизительным.
4. Whole-book PDF comparison шумный.

---

## 7. Как использовать в workflow

Правильная цепочка:

1. split source and target into chapters
2. normalize Unicode and styles
3. run `source_ru_comparator`
4. дать отчет в `Completeness Reviewer`
5. при наличии `target_reference_scan` собрать issue bundle для unresolved / format cases
6. по проблемным главам запускать `Meaning Reviewer`

---

## 8. Минимальный practical вывод

`source_ru_comparator` не заменяет редактора и не заменяет LLM review.  
Но он сильно сокращает область ручной проверки, потому что сразу показывает:

- где структура поехала;
- где вероятен пропуск;
- где вероятен лишний блок;
- где сломаны шлоки / списки / служебные элементы.
