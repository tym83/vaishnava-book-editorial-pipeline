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
