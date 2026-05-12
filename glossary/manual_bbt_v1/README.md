# Manual BBT Glossary v1

Это первый **ручной** `approved glossary`, собранный не от extractor-а, а от:

1. материалов из `~/Загрузки/корректура BBT`;
2. русских референсных книг Бхакти Викаши Свами;
3. локального `vedabase` по русским книгам.

## Статус

- файл [glossary_approved.csv](/home/tym83/Загрузки/Служение/Automate/glossary/manual_bbt_v1/glossary_approved.csv) считать текущим каноническим glossary source;
- старые `review_pack` и `review_pack_v2` считать extractor-derived archival material;
- `manual_bbt_v1` не зависит от auto-extraction для принятия решений.

## Что здесь есть

- утвержденные формы;
- курсивность;
- политика по диакритике;
- заметки по капитализации и склонению;
- разрешенные формы;
- нежелательные формы;
- safe automation flag для `DOCX` italic audit.

Сюда же входят локальные house-style решения поверх BBT base.
Например: `Гурудев` и `Гуру Махарадж`.

## Что здесь пока не делается

- полный охват всех терминов корпуса;
- автоматическое выведение всех падежных форм;
- автоматическое утверждение спорных случаев.

## Практическое применение

- `semantic_reviewer.py` читает `lemma_en` как список вариантов;
- `stylistic_reviewer.py` использует `discouraged_forms`;
- `docx_style_audit.py` использует `italic_automation=always|never`;
- `editorial_pipeline.py` передает этот glossary и в semantic/stylistic, и в style audit.
