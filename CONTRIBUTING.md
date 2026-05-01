# Contributing

## Scope

This repository is a workflow-and-tooling project, not a general-purpose library.

The priority order is:

1. editorial correctness;
2. deterministic automation;
3. traceable review artifacts;
4. compatibility with `DOCX` and `InDesign`.

## Ground Rules

- Prefer chapter-level workflows over whole-book processing.
- Do not silently change the theological meaning of text.
- Keep `Vedabase` as a reference layer, not as the final authority over approved publisher texts.
- Use structured reports and review bundles instead of ad hoc comments.

## Code Conventions

- CLI tools live in [scripts](./scripts).
- Repository-facing docs live in [docs](./docs).
- Original numbered design/spec documents stay in the repository root until a deliberate migration is done.
- Prefer ASCII in code unless the file already needs non-ASCII content.
- Keep scripts dependency-light and pragmatic.

## Tooling Assumptions

Some scripts rely on external desktop/CLI tools:

- `soffice`
- `pdftotext`
- `pdfinfo`
- `ghostscript`
- `Adobe InDesign` for `.jsx` execution

When changing a script, document any new external requirement in:

- [README.md](./README.md)
- [docs/GETTING_STARTED.md](./docs/GETTING_STARTED.md)

## Documentation Conventions

- Put short GitHub-friendly onboarding docs in [docs](./docs).
- Keep long-form workflow/spec references linked from [docs/README.md](./docs/README.md).
- When adding a new major script, update:
  - [README.md](./README.md)
  - [docs/SCRIPT_CATALOG.md](./docs/SCRIPT_CATALOG.md)
  - [10-script-specs.md](./10-script-specs.md), if the script is canonical

## Suggested Validation

Before publishing changes:

- run `python3 -m py_compile` on changed Python scripts;
- run a smoke-test command for each changed CLI entry point;
- if a review bundle format changed, test `docx_comment_applier.py` or the relevant applier.

