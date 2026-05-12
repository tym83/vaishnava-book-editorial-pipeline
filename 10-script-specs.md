# Script Specs v1

## 1. Общий принцип

Скрипты должны закрывать то, что:

- детерминируемо;
- повторяемо;
- плохо и дорого делать через LLM;
- можно проверять автоматически.

Технологический стек первой версии:

- `Python` для CLI-утилит;
- `JSX/ExtendScript` для InDesign 2022;
- при необходимости `LibreOffice` / `pandoc` / `python-docx`;
- без зависимости от слишком экзотических библиотек.

---

## 2. Скрипт: chapter-splitter

## Назначение

Разбить книгу на главы по `H1`.

## Вход

- `doc`
- `docx`
- `pdf`
- `idml`
- `indd` через экспорт/промежуточный слой, если нужно

## Выход

- `001.ext`
- `002.ext`
- ...

## Требования

- поддерживать ненумерованные H1;
- уметь резать предисловие/введение/приложения как отдельные блоки;
- не требовать manifest.

---

## 3. Скрипт: structure-normalizer

## Назначение

Привести текст к рабочей структуре:

- заголовки;
- шлоки;
- переводы шлок;
- письма;
- цитаты;
- источники;
- сноски;
- подписи к иллюстрациям;
- списки.

## Выход

Нормализованный промежуточный формат для дальнейшего анализа.

Рекомендуемый внутренний формат:

- `JSON`
- или `Markdown + markers`

Реализация v1:

- [structure_normalizer.py](/home/tym83/Загрузки/Служение/Automate/scripts/structure_normalizer.py)
- [text_structure.py](/home/tym83/Загрузки/Служение/Automate/scripts/text_structure.py)
- [vedabase_manifest.py](/home/tym83/Загрузки/Служение/Automate/scripts/vedabase_manifest.py)
- [vedabase_reference_resolver.py](/home/tym83/Загрузки/Служение/Automate/scripts/vedabase_reference_resolver.py)
- [vedabase_chapter_assembler.py](/home/tym83/Загрузки/Служение/Automate/scripts/vedabase_chapter_assembler.py)

Что уже умеет v1:

- нормализовать `vedabase` HTML в machine-readable JSON;
- вытаскивать секции:
  - `devanagari`
  - `verse_text`
  - `synonyms`
  - `translation`
  - `purport/commentary`
- нормализовать `doc/docx/txt/md/html`;
- отдавать единый block-schema, который уже может читать `source_ru_comparator`;
- добавлять block-level anchors:
  - `verse_id`
  - `source_locator`
- отдельно строить manifest по локальному зеркалу:
  - `page_type`
  - `chapter_key`
  - `assembly_mode`
  - наличие `advanced-view`
  - число найденных verse pages
- извлекать и резолвить шастрические ссылки:
  - `BG`
  - `SB`
  - `CC`
  - `ISO`
- использовать `vedabase` как reference layer, а не как основной source перевода
- при необходимости собирать chapter-level JSON как optional utility:
  - сначала из `advanced-view`
  - если его нет, то fallback по локально сохраненным verse pages

---

## 3.1. Скрипт: vedabase-manifest

## Назначение

Построить карту локального зеркала `vedabase`, чтобы следующий слой не работал вслепую по директориям.

## Что должен отдавать

- `web_path`
- `page_type`
- `work_id`
- `chapter_key`
- `verse_id`
- наличие/отсутствие `advanced-view`
- можно ли собрать главу автоматически:
  - `advanced_view`
  - `verse_pages`

## Практический смысл

Это слой для:

- аудита полноты зеркала;
- поиска verse-level и chapter-level входов;
- отделения реально отсутствующих данных от просто нескачанных `advanced-view`.

---

## 3.2. Скрипт: vedabase-reference-resolver

## Назначение

Использовать локальный `vedabase` как reference service для перевода, редактуры и spot-check review.

## Что должен уметь

- разбирать ссылки вида:
  - `БГ 1.2`
  - `ШБ 1.2.6`
  - `ЧЧ Мадхья 1.15`
  - `Ишо 1`
- резолвить их в локальные `vedabase` pages;
- сканировать `docx/txt/md/json/html`;
- смотреть не только body, но и footnotes/comments в `docx`;
- для каждого хита отдавать:
  - `resolved`
  - `unresolved`
  - `needs_normalization`
  - `canonical_display`
  - `replacement_text`
- отдавать resolved/unresolved summary для review-отчетов.

## Практический смысл

Это основной рабочий сценарий использования `vedabase` в пайплайне:

- сверка ссылок и цитат;
- точечный lookup по шлокам;
- помощь `unicode-normalizer` и review-скриптам в сомнительных местах;
- optional spot-check внутри `source_ru_comparator`.

---

## 3.3. Скрипт: vedabase-chapter-assembler

## Назначение

Собрать chapter-level JSON как вспомогательный кэш, когда reference-проверке нужен контекст целой главы.

## Источники

- сначала `advanced-view`
- если `advanced-view` не скачан, то локальные verse pages этой главы

## Что должен отдавать

- `metadata` по главе;
- flat `blocks` для текущих review-утилит;
- `verses[]` с `verse_id`, секциями и source anchors;
- флаг partial chapter, если в зеркале есть только часть стихов.

## Важная граница

Это не основной source для перевода книги.  
Это optional utility поверх `vedabase`, если review или AI-pass выгоднее работать с контекстом целой главы, а не с отдельными verse pages.

---

## 4. Скрипт: unicode-normalizer

## Назначение

Найти и заменить:

- `Gaura Times`-подобные legacy-символы;
- старую псевдодиакритику;
- кривые Unicode-последовательности;
- латиницу, случайно попавшую вместо кириллицы.

## Режимы

### Safe replace

Для очевидных механических замен.

### Review required

Для мест, где нужно сверять с `vedabase`.

---

## 5. Скрипт: glossary-candidate-extractor

## Назначение

Собрать кандидатов в глоссарий из:

- локального зеркала `vedabase`;
- книг БВКС;
- текущих рабочих переводов.

## Что извлекать

- имена;
- термины;
- названия;
- курсивные формы;
- варианты написаний;
- варианты склонений.

## Выход

- `CSV` с кандидатами;
- список конфликтов.

Реализация v1:

- [glossary_candidate_extractor.py](/home/tym83/Загрузки/Служение/Automate/scripts/glossary_candidate_extractor.py)

Практический результат v1:

- широкий draft:
  - `glossary_base_draft.csv`
- более полезный seed:
  - `glossary_seed_high_signal.csv`
- конфликтный список:
  - `glossary_conflicts.csv`
- summary:
  - `glossary_extraction_summary.md`

Следующий слой после extraction:

- `glossary_review_pack.py`
- `glossary_apply_review.py`

Важно:

- extraction больше не считать главным путем принятия glossary decisions;
- каноническая ручная база сейчас лежит в `glossary/manual_bbt_v1/glossary_approved.csv`;
- extractor остается полезным как вспомогательный discovery tool.

---

## 6. Скрипт: source-ru-comparator

## Назначение

Сравнить английскую главу с русской главой по полноте.

## Что проверять

- missing fragments;
- extra fragments;
- порядок крупных блоков;
- наличие сносок;
- базовое соответствие структуры.

## Выход

Не diff-файл сам по себе, а структурированные замечания, которые можно:

- показать редактору;
- преобразовать в comments;
- использовать в AI review.

## Важное ограничение

Лучше всего работает на:

- `DOCX/DOCX`
- на уровне главы
- после нормализации структуры и стилей

Новый допустимый режим:

- `normalized JSON` из `structure_normalizer.py` как machine-readable слой между source и review scripts
- optional scripture-reference spot-check через `vedabase_reference_resolver.py`

`PDF` допустим как fallback, но whole-book PDF comparison шумный и не должен считаться главным режимом.

---

## 7. Скрипт: old-ru-vs-new-en update helper

## Назначение

Поддержать сценарий:

- есть старая русская версия;
- есть новая английская версия;
- нужно найти сегменты для переперевода.

## Что должен делать

- находить changed segments;
- сопоставлять их со старым русским текстом;
- готовить список мест для обновления.

Реализация v1:

- [old_ru_vs_new_en_update_helper.py](/home/tym83/Загрузки/Служение/Automate/scripts/old_ru_vs_new_en_update_helper.py)

Практически в v1:

- normal mode: `old EN + new EN + old RU`;
- degraded mode: `new EN + old RU`, если старый EN недоступен;
- выход: `report json/md` и optional `issue bundle json`;
- режимы: `compare` и `compare-dir`.

---

## 7.1. Скрипт: semantic-reviewer

## Назначение

Собрать надежную semantic/theological review queue из high-confidence сигналов, не притворяясь полноценным “AI-судьей смысла”.

Реализация v1:

- [semantic_reviewer.py](/home/tym83/Загрузки/Служение/Automate/scripts/semantic_reviewer.py)

Практически в v1:

- использует `source_ru_comparator` как structural base;
- поднимает structural drift, aligned mismatches, reference issues;
- добавляет deterministic checks по числам, шастрическим ссылкам, цитатам и protected terms из approved glossary;
- `lemma_en` в approved glossary может быть списком вариантов через `|`;
- выход: `report json/md` и optional `issue bundle json`;
- режимы: `review` и `review-dir`.

---

## 7.2. Скрипт: stylistic-reviewer

## Назначение

Собрать русскую stylistic/proofreading очередь по surface-level, но надежным признакам.

Реализация v1:

- [stylistic_reviewer.py](/home/tym83/Загрузки/Служение/Automate/scripts/stylistic_reviewer.py)

Практически в v1:

- ловит OCR-помехи типа `Пра6хупада`, смешение латиницы/кириллицы;
- проверяет кавычки, скобки, пробелы, тире, многоточия, повторяющуюся пунктуацию;
- дает readability flags для длинных фраз;
- отдельно поднимает диакритику в прозе;
- может читать manual glossary и поднимать `discouraged_forms`;
- выход: `report json/md` и optional `issue bundle json`;
- режимы: `review` и `review-dir`.

---

## 7.3. Скрипт: editorial-pipeline

## Назначение

Склеить chapter-level модули в один production runner:

- prepare target copies;
- compare;
- semantic review;
- stylistic review;
- style audit;
- optional old-RU/new-EN update pass;
- merge issues;
- optional Word comments.

Реализация v1:

- [editorial_pipeline.py](/home/tym83/Загрузки/Служение/Automate/scripts/editorial_pipeline.py)

Практически в v1:

- режимы: `run-dir` и `run-book`;
- `run-book` умеет сначала split `doc/docx` по главам, потом запускать chapter pipeline;
- умеет делать non-destructive normalize passes для target:
  - `unicode_normalizer`
  - `docx_style_normalizer`
  - `docx_scripture_reference_normalizer`
- собирает merged issue bundle по главе;
- опционально применяет comments через `docx_comment_applier.py`;
- умеет подмешивать external issue bundles для поздних PDF/INDD стадий.

---

## 8. Скрипт: docx-style-audit

## Назначение

Проверить Word-документ перед импортом в InDesign.

## Что проверять

- есть ли все обязательные стили;
- есть ли ручное форматирование поверх стилей;
- есть ли локальные overrides;
- где используется просто `Ctrl+I` / `Ctrl+B`, а где символьный стиль;
- корректно ли размечены шлоки, письма, цитаты, подписи, сноски.
- safe glossary-driven italic policy для `always|never` случаев из manual BBT glossary.

## Выход

- отчет;
- список мест для правки.

---

## 8.1. Скрипт: docx-footnote-classifier

## Назначение

Привести Word-сноски к одному каноническому стилю:

- `Сноска`

## Рабочая семантика

В текущем стандарте текст сносок не делится на четыре типа. Все реальные абзацы сносок используют `Сноска`; legacy-стили `Сноска 1/2/3/4` нормализуются в `Сноска`.

## Что должен уметь

- работать с `docx` и `doc`
- переписывать стили в `word/footnotes.xml`
- строить `report md/json`
- экспортировать hints template
- поддерживать ручные hints для спорных случаев

---

## 8.2. Скрипт: docx-footnote-reference-normalizer

## Назначение

Нормализовать позицию маркеров сносок внутри основного текста.

Реализация:

- [docx_footnote_reference_normalizer.py](/home/tym83/Загрузки/Служение/Automate/scripts/docx_footnote_reference_normalizer.py)

## Что должен уметь

- работать с `docx` и `doc`;
- менять только `word/document.xml`;
- переставлять пунктуацию из формы `слово.<footnoteReference>` в `слово<footnoteReference>.`;
- не менять текст сносок в `word/footnotes.xml`;
- строить `report md/json` со списком измененных маркеров.

## Когда запускать

После style/dediacritic/style-enforcer проходов, если нужно точечно поправить позицию маркеров без изменения остального форматирования.

---

## 8.3. Скрипт: docx-style-enforcer

## Назначение

Подготовить DOCX к верстке так, чтобы визуальная геометрия жила в стилях, а не в ручном форматировании.

Реализация:

- [docx_style_enforcer.py](/home/tym83/Загрузки/Служение/Automate/scripts/docx_style_enforcer.py)

## Что делает

- задает параметры канонических блоковых стилей:
  - базовая гарнитура `Charis SIL` в `docDefaults` и во всех paragraph/character styles;
  - `Шлока`: левый отступ `2 см`, курсив, центр;
  - `Шлока в цитате`: левый отступ `3 см`, курсив, центр;
  - `Перевод шлоки`: левый отступ `2 см`;
  - `Цитата 1`: левый отступ `2 см`;
  - `Цитата 2`: левый отступ `3 см`;
- удаляет direct paragraph overrides из `pPr`;
- удаляет direct run overrides из `rPr`;
- сохраняет канонические символьные стили `Char Курсив` / `Char Полужирный`;
- сохраняет служебные стили ссылок сносок, если они нужны Word для структуры.

Для `docx_prose_dediacritizer.py`: стиль `Сноска` считается прозой по умолчанию. Диакритика в нем сохраняется только для явного самостоятельного санскритского блока, а имена и термины нормализуются без диакритики.

Для `docx_semantic_style_classifier.py`: визуальный блок считается по эффективному отступу `max(left, left + firstLine)`, чтобы строки шлок с висячим отступом не выпадали из стиля `Шлока`. Отдельные кавычечные абзацы с визуальным отступом классифицируются как `Цитата 1` без верхнего лимита в 180 слов.

## Когда запускать

После:

- `docx_footnote_classifier.py`;
- `docx_semantic_style_classifier.py`;
- `docx_prose_dediacritizer.py`.

Перед:

- финальным `docx_style_audit.py`;
- импортом в InDesign.

---

## 9. Скрипт: word-to-indesign-import

## Среда

Лучше всего как `JSX/ExtendScript` внутри InDesign 2022.

Реализация v1:

- [word_to_indesign_import.jsx](/home/tym83/Загрузки/Служение/Automate/scripts/word_to_indesign_import.jsx)

## Назначение

Импортировать `doc/docx` в `indd`-шаблон.

## Вход

- готовый `doc/docx`
- `indd`-шаблон

## Обязательные функции

- маппинг одноименных стилей Word -> InDesign;
- сохранение локального курсива;
- сохранение локального полужирного;
- перенос всех типов сносок;
- автоматическое разливание текста;
- добавление страниц, если текста больше, чем в шаблоне;
- игнорирование картинок на первой версии.

## Дополнительно

- лог по несопоставленным стилям;
- лог по overset;
- лог по проблемным блокам.

Практически в v1:

- пишется import report с новыми стилями после импорта;
- target story ищется по label `main_story` и запасным вариантам.

---

## 10. Скрипт: indesign-layout-qa

## Среда

`JSX/ExtendScript` внутри InDesign 2022.

Реализация v1:

- [indesign_layout_qa.jsx](/home/tym83/Загрузки/Служение/Automate/scripts/indesign_layout_qa.jsx)

## Назначение

Проверить готовую верстку.

## Что делать автоматически

- расставлять переносы;
- ставить неразрывные пробелы в типовых случаях;
- выполнять безопасные типографские чистки;
- искать obvious legacy-symbol problems.

Отдельно:

- проверять, что переносы включены и в сносках;
- маркировать подозрительные front-matter layout issues;
- различать inline-цитаты и большие самостоятельные цитатные блоки там, где это можно диагностировать структурно.

## Что не править молча

- потенциально смысловые изменения;
- спорные разрывы;
- места, где правка может поменять логику текста.

Такие места:
- помечать;
- комментировать.

## Что обязательно проверять

- overset text;
- missing fonts;
- style overrides;
- wrong language assignment;
- inconsistent hyphenation settings;
- footnote problems;
- widows/orphans (только маркировать).

## Что уже делает v1

- safe typography fixes:
  - безопасные `nbsp`;
  - привязка тире к предыдущему слову в обычной фразе;
  - переносы в body styles;
  - запрет переносов в заголовках и некоторых служебных стилях;
- report:
  - overset frames;
  - missing fonts;
  - hyphenation style issues;
  - paragraph/character overrides;
  - language issues;
  - legacy symbol issues;
  - footnote issues;
  - dangling dash suspects;
  - widow/orphan suspects;
  - front matter flags.

---

## 11. Скрипт: review-issue-bundle

## Назначение

Привести разные типы отчетов к единому issue schema, который потом можно:

- вставлять как Word comments;
- конвертировать в PDF annotations;
- применять как InDesign notes.

Реализация v1:

- [review_issue_bundle.py](/home/tym83/Загрузки/Служение/Automate/scripts/review_issue_bundle.py)

## Что поддерживается

- `from-comparator`
- `from-reference-scan`
- `from-style-audit`
- `from-semantic-report`
- `from-review-report`
- `from-footnote-report`
- `merge`

Дополнительно:

- `from-comparator` умеет подхватывать `target_reference_scan` из `source_ru_comparator` report;
- из reference scan поднимаются issue двух типов:
  - `scripture_reference_unresolved`
  - `scripture_reference_format`
- `from-reference-scan --unresolved-only` оставляет только реальные unresolved refs без format issues

## Что содержит bundle

- `version`
- `target_format`
- `target_path`
- `source_reports`
- `issues[]`

У issue есть:

- `id`
- `kind`
- `severity`
- `title`
- `message`
- `suggestion`
- `anchor`
- `context`
- `metadata`

Reference-aware issues используют те же anchors, что и `docx_comment_applier`:

- `part`
- `paragraph_index`
- при необходимости `container_id`

---

## 11.1. Скрипт: docx-scripture-reference-normalizer

## Назначение

Нормализовать формат шастрических ссылок прямо в `docx`, чтобы после повторного scan оставались только реальные unresolved cases.

Реализация v1:

- [docx_scripture_reference_normalizer.py](/home/tym83/Загрузки/Служение/Automate/scripts/docx_scripture_reference_normalizer.py)

## Что делает

- сканирует `document`, `footnotes`, `endnotes`, `comments`, headers/footers;
- приводит ссылки к каноническому виду:
  - `БГ 2.60`
  - `ШБ 1.2.6`
  - `ЧЧ Мадхья 17.14`
  - `Ишо 1`
- умеет исправлять не только single-node ссылки внутри одного `w:t`, но и split references, если ссылка разорвана соседними text runs;
- пишет `json/md` report по заменам.

## Ограничение v1

- multi-node rewrite сделан безопасно только для same-length reference forms;
- это нормализатор формата ссылки, а не валидатор смысла, цитаты или богословской корректности.

---

## 11.2. Скрипт: docx-scripture-reference-pipeline

## Назначение

Прогнать папку `docx` через повторяемый reference-cleanup flow:

1. `pre-scan`
2. auto-normalize
3. `post-scan`
4. unresolved-only issue bundle
5. optional commented editorial copy

Реализация v1:

- [docx_scripture_reference_pipeline.py](/home/tym83/Загрузки/Служение/Automate/scripts/docx_scripture_reference_pipeline.py)

## Что делает

- обходит один `docx` или целую директорию;
- сохраняет по каждому файлу:
  - `pre_scan.json/md`
  - `normalization.json/md`
  - `post_scan.json/md`
  - `unresolved_bundle.json`
- пишет общий:
  - `index.json/md`
  - `editorial_queue.json/md`
- по флагу `--apply-comments` создает `editorial-comments.docx` только для файлов, где после нормализации остались unresolved refs.

## Практический смысл

Это reference-side pre-review pass:

- format issues снимаются автоматически;
- в редакторскую очередь попадают только unresolved ссылки;
- остается audit trail, что именно было исправлено автоматически и что осталось на ручную проверку.

---

## 12. Скрипт: docx-comment-applier

## Назначение

Автоматически вносить замечания в `docx` как настоящие Word comments.

Реализация v1:

- [docx_comment_applier.py](/home/tym83/Загрузки/Служение/Automate/scripts/docx_comment_applier.py)

## Что делает

- читает issue bundle;
- создает или обновляет `word/comments.xml`;
- добавляет OOXML comment anchors в нужные абзацы;
- пишет `md/json` report по applied/skipped issues.

## На что умеет ссылаться

- `word/document.xml` по `paragraph_index`
- `word/footnotes.xml` по `paragraph_index`
- headers/footers/endnotes, если anchor указывает на соответствующий part

## Ограничение v1

- это paragraph-level comments, не range-level semantic diff;
- корректность открытия нужно валидировать реальным Word/LibreOffice на вашем контуре.

---

## 12.1. Скрипт: all-review-docx-builder

## Назначение

Собрать один редакторский `DOCX` книги со всеми слоями комментариев.

Реализация v1:

- [all_review_docx_builder.py](/home/tym83/Загрузки/Служение/Automate/scripts/all_review_docx_builder.py)

## Что делает

- принимает чистый `*.formatted.docx`;
- отказывается от входного DOCX с уже существующими комментариями, если явно не передан `--allow-existing-comments`;
- принимает несколько issue bundles: корректура, стили, semantic-style candidates, поверхностная сверка, глубокое EN/RU review;
- объединяет их через `review_issue_bundle.py merge`;
- применяет объединенный bundle через `docx_comment_applier.py`;
- проверяет `skipped == 0` по умолчанию;
- сверяет число примененных issues с фактическим числом `w:comment`;
- сохраняет итог как `*.all-review.docx`;
- при необходимости синхронизирует legacy-имена `*.review-comments.docx` и `*.master-review.docx` с тем же файлом.

## Правило

Для редактора финальный файл ревью должен быть один: `*.all-review.docx`. Промежуточные `md/json` отчеты и `review/deep_packs/*.md` являются audit trail, но не отдельным местом для внесения правок.

---

## 13. Скрипт: pdf-annotation-applier

## Назначение

Автоматически вносить review issues в `pdf` как sticky-note annotations.

Реализация v1:

- [pdf_annotation_applier.py](/home/tym83/Загрузки/Служение/Automate/scripts/pdf_annotation_applier.py)

## Технология

- `ghostscript pdfmark`
- без Python PDF-библиотек

## Что делает

- читает issue bundle;
- раскладывает page-level annotations по страницам;
- поддерживает явный `rect`, если он есть в anchor;
- по умолчанию ставит заметки в левом верхнем углу страницы со сдвигом по вертикали.

## Ограничение v1

- без координат это page-level annotation layer, а не paragraph-accurate layout diff;
- оптимально использовать для постверсточных замечаний с уже известными страницами.

---

## 14. Скрипт: indesign-note-applier

## Назначение

Автоматически превращать issue bundle в `InDesign notes`.

Реализация v1:

- [indesign_note_applier.jsx](/home/tym83/Загрузки/Служение/Automate/scripts/indesign_note_applier.jsx)

## Что делает

- открывает `indd` или берет активный документ;
- ищет story по `story_label` или fallback labels;
- привязывает issue к paragraph index или page;
- пытается создать настоящий InDesign note;
- если note API не срабатывает, пишет issue в paragraph/frame labels и фиксирует fallback в report.

## Ограничение v1

- `word/footnotes.xml` anchors не маппятся автоматически в layout-space;
- полноценную валидацию надо делать уже на машине с реальным `InDesign`.

---

## 15. Приоритет реализации скриптов

## 14.1. Project-specific Vibhava review helpers

Текущая книга `Śrī Bhaktisiddhānta Vaibhava`, Tom 1, использует отдельные helper-скрипты поверх общего pipeline:

- `vibhava_pdf_section_slicer.py`: режет английский PDF text layer на review sections;
- `vibhava_ru_review_section_slicer.py`: строит корректную RU review-нарезку на 84 секции, если часть заголовков в исходном split оказалась стилем `Основной текст`;
- `vibhava_translation_review_pack.py`: делает EN/RU side-by-side packs для смысловой сверки;
- `vibhava_review_comment_bundle.py`: превращает принятые review findings в issue bundle, anchored к полному DOCX книги.

Правило: после смыслового review результат должен быть применен к полной копии DOCX через `docx_comment_applier.py`; markdown packs не являются финальным редакторским deliverable.

---

### Первая волна

1. `chapter-splitter`
2. `unicode-normalizer`
3. `docx-style-audit`
4. `glossary-candidate-extractor`

### Вторая волна

5. `source-ru-comparator`
6. `old-ru-vs-new-en update helper`

### Третья волна

7. `word-to-indesign-import`
8. `indesign-layout-qa`

---

## 16. Критерии успеха

Скрипт считается удачным, если:

- уменьшает ручной труд;
- не ломает структуру;
- не скрывает ошибки;
- оставляет редактору контроль над смыслом;
- дает предсказуемый и повторяемый результат.
