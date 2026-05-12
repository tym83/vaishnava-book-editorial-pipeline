# Editor Decisions Log

## Как пользоваться

- сюда попадают уже утвержденные решения;
- спорные вещи сначала можно вносить как `proposed`;
- каждая запись должна быть короткой и проверяемой.

Шаблон:

```text
Date:
Status: approved | proposed | superseded
Type: RULE | EXCEPTION | TERM | STYLE | LAYOUT | SCRIPT | CHECK
Scope:
Decision:
Exceptions:
Source:
Updated files:
Notes:
```

---

## 2026-04-27

### Decision 001

Date: 2026-04-27
Status: approved
Type: RULE
Scope: общая русская корректура
Decision: буква `ё` используется везде как каноническая норма.
Exceptions: нет.
Source: переписка по проекту.
Updated files: `05-style-guide.md`, `08-qa-checklists.md`, prompt pack.
Notes: правило применяется и к новым переводам, и к корректуре существующих текстов.

### Decision 002

Date: 2026-04-27
Status: approved
Type: RULE
Scope: диакритика
Decision: диакритику по умолчанию сохраняем в шлоках, больших цитатах и разрешенных inline-цитатах; в обычной прозе снимаем.
Exceptions: короткие inline-цитаты и отдельные оговоренные случаи.
Source: переписка по проекту.
Updated files: `05-style-guide.md`, `08-qa-checklists.md`, `16-indesign-layout-qa-spec.md`, `docx_prose_dediacritizer.py`.
Notes: стандартные термины вроде `вани`, `вапу` остаются без диакритики.

### Decision 003

Date: 2026-04-27
Status: approved
Type: STYLE
Scope: Word/InDesign styles
Decision: локальный курсив и полужирный должны задаваться символьными стилями `Char Курсив` и `Char Полужирный`, а не только ручным форматированием.
Exceptions: legacy-документы до нормализации.
Source: переписка по проекту.
Updated files: `05-style-guide.md`, `10-script-specs.md`, `docx_style_normalizer.py`, `docx_style_audit.py`.
Notes: это нужно для предсказуемого Word -> InDesign импорта.

### Decision 004

Date: 2026-04-27
Status: approved
Type: LAYOUT
Scope: InDesign QA
Decision: строка не должна начинаться с повисшего тире внутри абзаца; layout QA должен это ловить и по возможности предотвращать безопасной привязкой тире к предыдущему слову.
Exceptions: диалоговое тире в начале абзаца.
Source: переписка по проекту.
Updated files: `16-indesign-layout-qa-spec.md`, `08-qa-checklists.md`, `indesign_layout_qa.jsx`.
Notes: эвристика репортит только не первые строки абзаца.

## 2026-05-11

### Decision 005

Date: 2026-05-11
Status: approved
Type: STYLE
Scope: Word/InDesign-ready DOCX
Decision: в production DOCX не оставлять ручные paragraph/run overrides; отступы, выравнивание, курсив, гарнитура и базовая геометрия задаются стилями. Базовая гарнитура — `Charis SIL`, не `Calibri`.
Exceptions: только технически необходимые DOCX-маркеры; спорный локальный курсив поднимается в review.
Source: обсуждение Vibhava Tom 1.
Updated files: `05-style-guide.md`, `04-master-workflow.md`, `docx_style_enforcer.py`, `docx_style_audit.py`.
Notes: `docx_style_enforcer.py` является обязательным перед финальным style audit.

### Decision 006

Date: 2026-05-11
Status: approved
Type: STYLE
Scope: шлоки, цитаты, переводы шлок
Decision: `Шлока` получает отступ `2 см`, курсив и центрирование; отдельные цитаты и переводы шлок получают отступ `2 см`; каждый следующий уровень вложенности добавляет `1 см`.
Exceptions: третий и последующие уровни требуют отдельного стиля или явного расширения style set.
Source: обсуждение Vibhava Tom 1.
Updated files: `05-style-guide.md`, `docx_style_enforcer.py`, `docx_semantic_style_classifier.py`.
Notes: визуальный отступ без семантического стиля не считается достаточным.

### Decision 007

Date: 2026-05-11
Status: approved
Type: STYLE
Scope: сноски
Decision: весь текст сносок в Vibhava Tom 1 одного типа и должен использовать единый стиль `Сноска`; legacy-варианты `Сноска 1`–`Сноска 4` сворачиваются в `Сноска`.
Exceptions: нет для текущей книги.
Source: обсуждение Vibhava Tom 1.
Updated files: `05-style-guide.md`, `docx_footnote_classifier.py`.
Notes: если в другой книге появятся реальные типы сносок, это фиксируется отдельным решением.

### Decision 008

Date: 2026-05-11
Status: approved
Type: STYLE
Scope: маркеры сносок в основном тексте
Decision: номер сноски ставится после слова/фразы, но перед следующим знаком препинания: `слово¹.`, не `слово.¹`.
Exceptions: нет.
Source: обсуждение Vibhava Tom 1.
Updated files: `05-style-guide.md`, `04-master-workflow.md`, `docx_footnote_reference_normalizer.py`.
Notes: правило применяется автоматическим pass после style enforcement.

### Decision 009

Date: 2026-05-11
Status: approved
Type: CHECK
Scope: проверка перевода EN/RU
Decision: смысловое ревью не считается завершенным, если замечания остались только во внешнем markdown-отчете; рабочий результат для редактора — полный DOCX книги с Word-комментариями.
Exceptions: markdown/json отчеты остаются техническим логом и промежуточным audit trail.
Source: обсуждение Vibhava Tom 1.
Updated files: `04-master-workflow.md`, `21-review-annotation-workflow.md`, `vibhava_review_comment_bundle.py`, `docx_comment_applier.py`.
Notes: комментарий должен включать проблему, причину и suggested fix.

### Decision 010

Date: 2026-05-11
Status: approved
Type: CHECK
Scope: feedback loop после редакторской правки
Decision: принятые/отклоненные редактором замечания должны возвращаться в pipeline как обновления issue bundles, глоссария и decision log; просто diff без фиксации решений недостаточен для обучения следующего прогона.
Exceptions: одноразовые опечатки можно закрывать только в отчете, если они не создают правило.
Source: обсуждение Vibhava Tom 1.
Updated files: `04-master-workflow.md`, `21-review-annotation-workflow.md`, `18-editor-decisions-log.md`.
Notes: повторяемые терминологические решения переносятся в glossary, структурные — в scripts/style rules.

### Decision 011

Date: 2026-05-11
Status: approved
Type: TERM
Scope: названия журналов, газет и аналогичных изданий
Decision: названия периодических изданий сохраняются в оригинале, если нет утвержденного русского исключения.
Exceptions: зафиксированные в glossary/decision log русские названия.
Source: review Vibhava Tom 1, секция 001 (`Harmonist`).
Updated files: `05-style-guide.md`, `ai_review_pilot_001_005.md`, `vibhava_review_comment_bundle.py`.
Notes: `Harmonist` не переводить автоматически как `Гармонизатор`.

### Decision 012

Date: 2026-05-11
Status: approved
Type: CHECK
Scope: итоговые файлы ревью для редактора
Decision: все сформированные замечания по книге должны попадать в один рабочий DOCX `*.all-review.docx`: корректура, форматирование, semantic-style candidates, поверхностное ревью и глубокое EN/RU translation review.
Exceptions: `review/deep_packs/*.md`, issue bundles и json/md отчеты остаются техническим audit trail; они не являются отдельным местом для внесения редакторских правок.
Source: обсуждение двух книг Vamshidasa Babaji и Jaya Srila Prabhupada.
Updated files: `21-review-annotation-workflow.md`, `output/two_books_processing_summary.md`.
Notes: legacy-имена `*.review-comments.docx` и `*.master-review.docx`, если сохраняются, должны быть синхронизированы с `*.all-review.docx`, чтобы редактор не работал в разных версиях.
