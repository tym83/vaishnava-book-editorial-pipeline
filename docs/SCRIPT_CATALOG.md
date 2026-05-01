# Script Catalog

This is the practical map of the main automation modules.

## Core Ingest and Structure

- [../scripts/chapter_splitter.py](../scripts/chapter_splitter.py)  
  Split books into chapter files.
- [../scripts/structure_normalizer.py](../scripts/structure_normalizer.py)  
  Normalize source formats into machine-readable JSON.
- [../scripts/text_structure.py](../scripts/text_structure.py)  
  Shared structured text extraction layer.
- [../scripts/unicode_normalizer.py](../scripts/unicode_normalizer.py)  
  Replace legacy encoding and normalize Unicode.

## `Vedabase` Reference Layer

- [../scripts/vedabase_manifest.py](../scripts/vedabase_manifest.py)  
  Build a mirror manifest.
- [../scripts/vedabase_reference_resolver.py](../scripts/vedabase_reference_resolver.py)  
  Resolve scripture references against local `Vedabase`.
- [../scripts/vedabase_chapter_assembler.py](../scripts/vedabase_chapter_assembler.py)  
  Optional chapter-level cache builder.

## Comparison and Update

- [../scripts/source_ru_comparator.py](../scripts/source_ru_comparator.py)  
  Structural `source vs RU` completeness review.
- [../scripts/old_ru_vs_new_en_update_helper.py](../scripts/old_ru_vs_new_en_update_helper.py)  
  Find old RU segments that likely need updates from new EN.

## Review Queue Builders

- [../scripts/semantic_reviewer.py](../scripts/semantic_reviewer.py)  
  Deterministic semantic/theological review queue.
- [../scripts/stylistic_reviewer.py](../scripts/stylistic_reviewer.py)  
  Russian stylistic/proofreading review queue.
- [../scripts/docx_style_audit.py](../scripts/docx_style_audit.py)  
  Audit `DOCX` style hygiene before import.
- [../scripts/docx_footnote_classifier.py](../scripts/docx_footnote_classifier.py)  
  Classify footnotes into canonical styles.

## Style and Reference Cleanup

- [../scripts/docx_style_normalizer.py](../scripts/docx_style_normalizer.py)  
  Normalize paragraph and character styles.
- [../scripts/docx_semantic_style_classifier.py](../scripts/docx_semantic_style_classifier.py)  
  Heuristic semantic style assignment.
- [../scripts/docx_prose_dediacritizer.py](../scripts/docx_prose_dediacritizer.py)  
  Remove Sanskrit diacritics from prose.
- [../scripts/docx_scripture_reference_normalizer.py](../scripts/docx_scripture_reference_normalizer.py)  
  Normalize scripture reference formatting.
- [../scripts/docx_scripture_reference_pipeline.py](../scripts/docx_scripture_reference_pipeline.py)  
  Batch reference cleanup for chapter corpora.

## Glossary Workflow

- [../scripts/glossary_candidate_extractor.py](../scripts/glossary_candidate_extractor.py)  
  Extract glossary candidates from corpus/reference sources.
- [../scripts/glossary_review_pack.py](../scripts/glossary_review_pack.py)  
  Prepare human review pack.
- [../scripts/glossary_apply_review.py](../scripts/glossary_apply_review.py)  
  Build approved glossary artifacts from reviewed CSV.

## Review-Issue and Annotation Layer

- [../scripts/review_issue_utils.py](../scripts/review_issue_utils.py)  
  Shared issue helpers.
- [../scripts/review_issue_bundle.py](../scripts/review_issue_bundle.py)  
  Convert reports into issue bundles.
- [../scripts/docx_comment_applier.py](../scripts/docx_comment_applier.py)  
  Apply issue bundles as Word comments.
- [../scripts/pdf_annotation_applier.py](../scripts/pdf_annotation_applier.py)  
  Apply issue bundles as PDF sticky notes.
- [../scripts/indesign_note_applier.jsx](../scripts/indesign_note_applier.jsx)  
  Apply issue bundles as `InDesign` notes/labels.

## Orchestration

- [../scripts/editorial_review_common.py](../scripts/editorial_review_common.py)  
  Shared helpers for review reports and bundles.
- [../scripts/editorial_pipeline.py](../scripts/editorial_pipeline.py)  
  End-to-end chapter pipeline runner.

## InDesign Import and QA

- [../scripts/word_to_indesign_import.jsx](../scripts/word_to_indesign_import.jsx)  
  Import `Word -> InDesign`.
- [../scripts/indesign_layout_qa.jsx](../scripts/indesign_layout_qa.jsx)  
  Post-import layout QA.

