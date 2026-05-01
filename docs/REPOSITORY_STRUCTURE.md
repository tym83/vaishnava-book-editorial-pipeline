# Repository Structure

## Top Level

```text
Automate/
├── scripts/
├── docs/
├── glossary/
├── hints/
├── review_issues/
├── 01-user-request.md
├── 02-proposed-project-structure.md
├── ...
├── 21-review-annotation-workflow.md
├── README.md
├── CONTRIBUTING.md
└── requirements.txt
```

## Directory Roles

### `scripts/`

Canonical implementation layer.

Contains:

- Python CLI tools;
- shared helpers;
- InDesign `.jsx` automation.

### `docs/`

GitHub-friendly navigation layer.

Contains:

- onboarding docs;
- repo structure docs;
- script catalog;
- suggested GitHub metadata.

### `glossary/`

Glossary data and review artifacts.

Contains:

- draft glossary exports;
- conflicts;
- review packs;
- approved/dropped outputs when generated.

### `hints/`

Manual hints for heuristic classifiers.

Typical use:

- semantic style classifier hints;
- footnote classification hints.

### `review_issues/`

Shared issue-bundle templates and related schema artifacts.

## Root Markdown Files

The numbered root Markdown files are the original design/spec corpus.

Current practical rule:

- keep them in the root for traceability;
- link to them from `docs/README.md`;
- add new GitHub-facing navigation docs to `docs/`.

## Recommended Future Evolution

Not required immediately, but the likely next cleanup is:

```text
docs/
  architecture/
  workflows/
  specs/
```

At the moment, this repository uses a lighter approach: keep canonical source docs where they already are, and add a curated docs layer above them.

