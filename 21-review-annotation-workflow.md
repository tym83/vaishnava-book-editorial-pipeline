# Review Annotation Workflow v1

## 1. Цель

Этот слой нужен, чтобы превращать уже существующие результаты проверки:

- comparator reports;
- style audit reports;
- semantic review reports;
- footnote review reports;
- layout QA findings;

в реальные review artifacts внутри рабочих файлов:

- Word comments в `docx`;
- sticky-note annotations в `pdf`;
- notes или fallback labels в `indd`.

---

## 2. Общая схема

```text
report json/md
-> review_issue_bundle.py
-> issue bundle json
-> format-specific applier
```

Где format-specific applier:

- `docx_comment_applier.py`
- `pdf_annotation_applier.py`
- `indesign_note_applier.jsx`

---

## 3. Единый issue schema

## Top-level

```json
{
  "version": 1,
  "target_format": "docx",
  "target_path": "/path/to/file.docx",
  "source_reports": ["/path/to/report.json"],
  "issues": []
}
```

Готовый шаблон:

- [issue_bundle_template.json](/home/tym83/Загрузки/Служение/Automate/review_issues/issue_bundle_template.json)

## Issue

```json
{
  "id": "cmp-struct-0001",
  "kind": "struct_delete",
  "severity": "warning",
  "title": "Возможный пропуск перевода",
  "message": "…",
  "suggestion": "…",
  "anchor": {},
  "context": {},
  "metadata": {}
}
```

## Anchor fields

В зависимости от формата и источника могут использоваться:

- `part`
- `paragraph_index`
- `footnote_id`
- `page`
- `rect`
- `story_label`

---

## 4. Конвертер issue bundles

Скрипт:

- [review_issue_bundle.py](/home/tym83/Загрузки/Служение/Automate/scripts/review_issue_bundle.py)

Поддерживает:

- `from-comparator`
- `from-style-audit`
- `from-semantic-report`
- `from-review-report`
- `from-footnote-report`
- `merge`

### Пример: comparator -> bundle

```bash
python3 review_issue_bundle.py from-comparator \
  compare.json issues.json \
  --target-format docx \
  --target-path /path/to/chapter.docx
```

### Пример: style audit -> bundle

```bash
python3 review_issue_bundle.py from-style-audit \
  audit.json issues.json \
  --target-path /path/to/chapter.docx
```

### Пример: generic review report -> bundle

```bash
python3 review_issue_bundle.py from-review-report \
  semantic.json issues.json \
  --target-path /path/to/chapter.docx
```

### Пример: merge

```bash
python3 review_issue_bundle.py merge \
  merged.json a.json b.json c.json
```

---

## 5. DOCX comments

Скрипт:

- [all_review_docx_builder.py](/home/tym83/Загрузки/Служение/Automate/scripts/all_review_docx_builder.py) — финальный сборщик одного `*.all-review.docx`;
- [docx_comment_applier.py](/home/tym83/Загрузки/Служение/Automate/scripts/docx_comment_applier.py)

### Что делает

- создает `word/comments.xml`, если его нет;
- добавляет comment relationships и content type override;
- ставит paragraph-level Word comments.

### Пример

```bash
python3 docx_comment_applier.py apply \
  input.docx issues.json output.docx \
  --author Codex \
  --initials CX \
  --report-md report.md \
  --report-json report.json
```

### Когда использовать

- редактура в Word;
- корректура в Word;
- полнота перевода и style audit на `docx`.

### Правило для EN/RU translation review

Для редактора основной результат проверки перевода — полный `DOCX` книги с Word-комментариями. Внешние `md/json` отчеты являются логом, но не заменяют annotated DOCX.

Итоговый файл для ручной работы редактора должен быть один: `*.all-review.docx`. В нем должны быть объединены все слои комментариев:

- корректура;
- стилевые и структурные замечания;
- semantic-style candidates;
- поверхностная сверка;
- глубокое EN/RU translation review.

Файлы `review/deep_packs/*.md`, промежуточные issue bundles и отдельные `review-comments`/`master-review` имена не должны создавать параллельные рабочие версии. Если такие имена сохраняются для совместимости, они должны быть синхронизированы с `*.all-review.docx`.

Если проверка велась по chapter/section packs:

1. собрать findings в `issue bundle`;
2. привязать anchors к абзацам полного DOCX;
3. собрать итоговый файл через `all_review_docx_builder.py build`;
4. при необходимости передать legacy-имена через `--legacy-copy`;
5. проверить `applied/skipped`; skipped должен быть `0` перед передачей файла редактору.

### Layered review passes

Повторные прогоны не должны удалять предыдущие комментарии. Новый проход фиксируется отдельным findings-файлом и подключается в сборщик поверх старых findings.

Текущий пример для Vaibhava Tom 1:

- base/pilot findings живут в [scripts/vibhava_review_comment_bundle.py](./scripts/vibhava_review_comment_bundle.py);
- первый расширенный слой живет в [docs/vibhava_tom1_review_findings_extra.json](./docs/vibhava_tom1_review_findings_extra.json);
- второй глубокий prose-review слой живет в [docs/vibhava_tom1_review_findings_deep_prose.json](./docs/vibhava_tom1_review_findings_deep_prose.json);
- итоговый DOCX должен собираться заново из чистого style-enforced DOCX, а не путем редактирования уже прокомментированного файла;
- после сборки обязательно проверить `applied/skipped`, количество `w:comment`, `w:commentReference`, `w:commentRangeStart`, `w:commentRangeEnd`; все четыре счетчика должны совпадать.

Каждый комментарий должен содержать:

- тип проблемы;
- почему это проблема;
- suggested fix.

### Feedback loop

После ручных правок редактора:

- принятые терминологические решения переносятся в glossary;
- повторяемые правила переносятся в `18-editor-decisions-log.md` и style/workflow docs;
- rejected/false-positive comments фиксируются, чтобы не повторять их в следующем прогоне;
- простой diff полезен как материал, но не заменяет явную фиксацию решений.

---

## 6. PDF annotations

Скрипт:

- [pdf_annotation_applier.py](/home/tym83/Загрузки/Служение/Automate/scripts/pdf_annotation_applier.py)

### Что делает

- применяет issue bundle к PDF через `ghostscript pdfmark`;
- создает sticky-note annotations;
- поддерживает page-level anchors и explicit rect.

### Пример

```bash
python3 pdf_annotation_applier.py apply \
  input.pdf issues.json output.pdf \
  --author Codex \
  --report-md report.md \
  --report-json report.json
```

### Когда использовать

- поздняя постверсточная проверка;
- корректорские замечания уже по страницам;
- review PDF, который напрямую не редактируется.

---

## 7. InDesign notes

Скрипт:

- [indesign_note_applier.jsx](/home/tym83/Загрузки/Служение/Automate/scripts/indesign_note_applier.jsx)

### Что делает

- читает issue bundle;
- пытается вставить настоящий note в `InDesign`;
- fallback: пишет содержимое issue в labels и фиксирует это в report.

### Параметры через `app.scriptArgs`

- `input`
- `issues`
- `report`
- `report_json`
- `save_after`
- `labels`

### Когда использовать

- review внутри `indd`;
- post-import cleanup;
- ручной проход дизайнера/редактора по note anchors.

---

## 8. JSON из layout QA

Скрипт:

- [indesign_layout_qa.jsx](/home/tym83/Загрузки/Служение/Automate/scripts/indesign_layout_qa.jsx)

Теперь пишет:

- `*.layout-qa-report.md`
- `*.layout-qa-report.json`

Если `report_json` явно не задан, рядом с markdown-отчетом пишется JSON-файл с тем же basename.

Это сделано, чтобы дальше можно было:

- конвертировать findings в issue bundle;
- применять их как PDF annotations или InDesign notes.

---

## 9. Практический порядок использования

## DOCX

1. Прогнать нужные анализаторы.
2. Собрать issue bundle.
3. Применить `docx_comment_applier.py`.
4. Отдать редактору/корректору уже комментированный файл.

## PDF

1. Иметь page-aware issues.
2. Собрать или руками подготовить issue bundle.
3. Применить `pdf_annotation_applier.py`.
4. Смотреть уже аннотированный PDF.

## INDD

1. Импортировать `docx`.
2. Прогнать `indesign_layout_qa.jsx`.
3. Подготовить issue bundle.
4. Применить `indesign_note_applier.jsx`.

---

## 10. Ограничения v1

1. Автоматический `report -> bundle` пока покрывает не все типы отчетов.
2. `pdf`-аннотации без координат page-level, а не paragraph-accurate.
3. `indesign_note_applier.jsx` требует реального smoke test на вашей версии InDesign.
4. Footnote-level anchors из Word не маппятся напрямую в layout-space.
