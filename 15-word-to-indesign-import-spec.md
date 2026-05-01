# Word to InDesign Import Spec v1

## 1. Скрипт

- [word_to_indesign_import.jsx](/home/tym83/Загрузки/Служение/Automate/scripts/word_to_indesign_import.jsx)

Среда:

- `InDesign 2022`
- `JSX / ExtendScript`

---

## 2. Что делает v1

Скрипт:

1. открывает `INDD`-шаблон;
2. включает smart text reflow;
3. находит основную текстовую рамку;
4. очищает её story chain;
5. помещает подготовленный `DOCX/DOC` в story;
6. сохраняет новый `INDD`;
7. пишет короткий import-report.

---

## 3. Предпосылки

Перед запуском желательно уже пройти:

1. `unicode_normalizer`
2. `docx_style_normalizer`
3. `docx_semantic_style_classifier`
4. `docx_prose_dediacritizer`
5. `docx_footnote_classifier`
6. `docx_style_audit`

Иначе импортёр будет работать, но мусор и нестабильные стили переедут в `InDesign`.

---

## 4. Как определяется target story

Приоритет:

1. текстовая рамка с label:
   - `main_story`
   - `main-story`
   - `main_text`
   - `mainText`
2. первая незаблокированная text frame на первой странице;
3. первая незаблокированная text frame документа.

Практический вывод:

- в шаблоне лучше явно помечать главную цепочку рамок label `main_story`.

---

## 5. Что сохраняется

Ожидаемое поведение:

- абзацные стили Word -> InDesign по совпадающим именам;
- локальный курсив;
- локальный полужирный;
- footnotes/endnotes, если InDesign их принимает через текущие import prefs.

---

## 6. Что пишет report

В import report попадает:

- template path
- input docx path
- output indd path
- target frame/page
- pages before/after
- pages added
- story overset flag
- новые paragraph styles после импорта
- новые character styles после импорта

Если после импорта появились новые стили, это сигнал, что:

- либо имена стилей не совпали;
- либо InDesign создал конфликтные дубликаты;
- либо Word-документ содержал неожиданные стили.

---

## 7. Ограничения v1

1. Скрипт не диагностирует все причины style conflicts.
2. Он не занимается картинками.
3. Он не перестраивает сложный шаблон автоматически.
4. Он не решает дизайнерские вопросы front matter / spreads.
5. Он не гарантирует правильный импорт, если в шаблоне нет нормальной story chain.

---

## 8. Практический режим использования

### Рекомендуемый сценарий

1. Подготовить `docx`.
2. Проверить аудитом стилей.
3. В шаблоне `indd` пометить главную рамку label `main_story`.
4. Запустить `word_to_indesign_import.jsx`.
5. Проверить import report.
6. Затем прогнать layout QA.

---

## 9. Как запускать

### Вариант 1. Через диалоги InDesign

Запустить скрипт, затем руками выбрать:

- template `.indd`
- input `.docx`
- output `.indd`

### Вариант 2. Через `app.scriptArgs`

Можно передавать:

- `template`
- `input`
- `output`
- `report`
- `labels`
- `clear_existing`
- `show_import_options`

---

## 10. Что делать дальше

После v1 логичный следующий шаг:

1. добавить более точный target-story selection;
2. добавить overset/page diagnostics;
3. добавить post-import cleanup/report for duplicate styles;
4. затем писать `indesign-layout-qa.jsx`.
