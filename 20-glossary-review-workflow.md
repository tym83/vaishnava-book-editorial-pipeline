# Glossary Review Workflow v3

## 1. Канонический порядок

Главный путь теперь такой:

1. взять BBT rule docs из `~/Загрузки/корректура BBT`;
2. вручную выбрать и нормализовать термины;
3. сверить их по референсным русским книгам Бхакти Викаши Свами;
4. дополнить русскими примерами из локального `vedabase`;
5. собрать `approved glossary` напрямую.

Это важнее, чем старый extractor-first workflow.

## 2. Канонический файл

Основной рабочий glossary сейчас:

- [manual_bbt_v1/glossary_approved.csv](/home/tym83/Загрузки/Служение/Automate/glossary/manual_bbt_v1/glossary_approved.csv)

Сопроводительные правила:

- [manual_bbt_v1/BBT_STYLE_RULES.md](/home/tym83/Загрузки/Служение/Automate/glossary/manual_bbt_v1/BBT_STYLE_RULES.md)
- [manual_bbt_v1/README.md](/home/tym83/Загрузки/Служение/Automate/glossary/manual_bbt_v1/README.md)

## 3. Что считать legacy

Эти файлы больше не считаются каноническим review set:

- [glossary/review_pack_v2/glossary_review_master.csv](/home/tym83/Загрузки/Служение/Automate/glossary/review_pack_v2/glossary_review_master.csv)
- [glossary/review_pack/glossary_review_master.csv](/home/tym83/Загрузки/Служение/Automate/glossary/review_pack/glossary_review_master.csv)

Они полезны как:

- архив extraction;
- список кандидатов;
- источник шумных вариантов для дальнейшей ручной фильтрации.

## 4. Новые поля, которые реально используются

В ручном glossary важны не только старые поля, но и:

- `allowed_forms`
- `discouraged_forms`
- `italic_automation`

Смысл:

- `allowed_forms`:
  допустимые формы и устойчивые варианты;
- `discouraged_forms`:
  формы, которые надо поднимать как review issue;
- `italic_automation`:
  только safe automation для `DOCX` style audit:
  `always`, `never`, `skip`.

## 5. Что делает код

- `semantic_reviewer.py`:
  читает `lemma_en` как список английских вариантов через `|`
- `stylistic_reviewer.py`:
  ищет `discouraged_forms`
- `docx_style_audit.py`:
  проверяет safe BBT italic policy
- `editorial_pipeline.py`:
  прокидывает glossary во все три слоя

## 6. Как расширять glossary дальше

1. Не запускать auto-extractor как источник решений.
2. Открывать BBT docs и добавлять term вручную.
3. Проверять хотя бы один пример в БВКС.
4. Проверять хотя бы один пример в `vedabase` RU, если термин там есть.
5. Если случай неоднозначный:
   не ставить `always|never`, а оставлять `skip`.

## 7. Когда возвращаться к extraction

Только после того, как:

- `manual_bbt_v1` станет достаточно плотной базой;
- будут ясны blacklist rules;
- будут ясны alias rules;
- будет понятно, какие категории extractor действительно может поднимать без сильного шума.
