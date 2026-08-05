# Tasks: Transcript Translation

## 1. Translation Module Core

- [x] 1.1 Create `shared/translate.py` with `TranslationConfig` dataclass and `TranslationResult` / `DetectionResult` dataclasses
  - `TranslationConfig`: `enabled`, `api_key`, `base_url`, `model` (default `claude-sonnet-4-6`), `supported_languages` (default `["fr", "de", "es"]`)
  - `TranslationResult`: `markdown`, `translated`, `source_language`, `detected_languages`, `confidence`, `error`
  - `DetectionResult`: `language`, `confidence`, `detected_languages`, `needs_translation`
  - Add helper `TranslationConfig.from_env(enabled: bool)` to load from `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL`
  - Raise `ValueError` if `enabled=True` but `ANTHROPIC_API_KEY` is not set
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

- [x] 1.2 Implement `detect_language(text: str) -> DetectionResult` in `shared/translate.py`
  - Strip markdown formatting (headings, bold, bullets, timestamps, speaker names, block anchors `^t-N`) to extract plain prose
  - Split cleaned text into 3 equal sections (beginning, middle, end)
  - Run `langdetect.detect_langs()` on each section with `DetectorFactory.seed = 0`
  - Aggregate: if any section detects fr/de/es at >0.7 confidence and that language covers >10% of total text → `needs_translation=True`
  - Collect all non-English supported languages into `detected_languages`
  - On exception or empty text → return `language="en"`, `needs_translation=False`
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3b.1, 3b.3_

- [x] 1.3 Implement `_translate_body(body: str, detected_languages: list[str], config: TranslationConfig) -> str` in `shared/translate.py`
  - Create `anthropic.Anthropic(api_key=config.api_key, base_url=config.base_url)`
  - System prompt: translate non-English content to English, preserve markdown formatting, speaker names, timestamps, block anchors, Obsidian syntax; return only translated text
  - Include `detected_languages` in the prompt so Claude knows which languages to expect
  - `max_tokens = min(len(body) * 3, 16384)`
  - Timeout: 60s via `anthropic` client `timeout` param
  - On 429: retry once after 10s, then raise
  - _Requirements: 1.1, 1.3, 3b.2, 4.3, 6.2, 6.3, 6.4_

- [x] 1.4 Implement `translate_markdown(markdown: str, config: TranslationConfig) -> TranslationResult` in `shared/translate.py`
  - Split markdown into frontmatter and body (split on `---` delimiters)
  - Call `detect_language(body)`
  - If `not detection.needs_translation` → return original with `translated=False`
  - Call `_translate_body(body, detection.detected_languages, config)`
  - Inject into frontmatter: `original_language`, `translated: true`, and `original_languages` list if multiple languages detected
  - Prepend `> *Auto-translated from [Language(s)]*` after frontmatter
  - On translation error: return original markdown with `translated: false` and `translation_error` in frontmatter
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 5.1, 5.2_

- [x] 1.5 Checkpoint — Unit tests for translation module pass
  - Run `pytest tests/unit/test_translate.py`
  - _Requirements: 3.1, 3.4, 3b.1, 3b.3_

## 2. Unit Tests

- [x] 2.1 Create `tests/unit/test_translate.py` with detection tests
  - Test `detect_language()` with pure French text → `language="fr"`, `needs_translation=True`
  - Test with pure English text → `language="en"`, `needs_translation=False`
  - Test with empty text → `language="en"`, `needs_translation=False`
  - Test with English first half + French second half → `needs_translation=True`, `detected_languages=["fr"]`
  - Test with French + German sections → `detected_languages=["fr", "de"]`
  - Test with unsupported language (e.g., Japanese) → `needs_translation=False`, log warning
  - Test markdown stripping: headings, timestamps, speaker names don't pollute detection
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3b.1, 3b.3_

- [x] 2.2 Create tests for `translate_markdown()` in `tests/unit/test_translate.py`
  - Mock `anthropic.Anthropic` client with `unittest.mock.patch`
  - Test: French body → frontmatter gets `original_language: fr`, `translated: true`, body is translated
  - Test: English body → returned unchanged, no translation fields in frontmatter
  - Test: Mixed English+French → `original_language: fr`, `translated: true`
  - Test: Mixed French+German → `original_languages: [fr, de]` in frontmatter
  - Test: API failure → original content returned with `translated: false`, `translation_error` set
  - Test: frontmatter edge cases (no frontmatter, empty body, multi-line YAML values)
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 5.1, 5.2_

- [x] 2.3 Checkpoint — All unit tests pass
  - Run `pytest tests/`
  - _Requirements: all_

## 3. Dependencies

- [x] 3.1 Add `langdetect` and `anthropic` to `pyproject.toml` as optional `[translate]` extra
  - `[project.optional-dependencies]` → `translate = ["langdetect>=1.0.9", "anthropic>=0.40.0"]`
  - _Requirements: 6.2_

## 4. CLI Integration

- [x] 4.1 Add `--translate` flag to `fathom sync` command in `cli.py`
  - Add `@click.option("--translate", is_flag=True, help="Translate non-English transcripts to English")`
  - Build `TranslationConfig.from_env(enabled=translate)` — exit with error if key missing
  - Pass `translate_config` to `fathom.sync.run_sync()`
  - _Requirements: 6.1, 6.5, 6.6_

- [x] 4.2 Add `--translate` flag to `gmeet sync` command in `cli.py`
  - Same pattern as 4.1 for the gmeet sync command
  - Pass `translate_config` to `gmeet.sync.run_sync()`
  - _Requirements: 6.1, 6.5, 6.6_

## 5. Sync Pipeline Integration

- [x] 5.1 Wire translation into `fathom/sync.py` `run_sync()`
  - Add `translate_config: TranslationConfig | None = None` parameter
  - After `markdown = meeting_to_markdown(meeting)` and before `atomic_write()`:
    - If `translate_config and translate_config.enabled`: call `translate_markdown(markdown, translate_config)`
    - Update `markdown` with result, log translation outcome
  - Same integration in `export_single()`
  - _Requirements: 1.1, 4.1, 5.1, 5.3_

- [x] 5.2 Wire translation into `gmeet/sync.py` `run_sync()`
  - Add `translate_config: TranslationConfig | None = None` parameter
  - After `markdown = meeting_to_markdown(match)` and before `atomic_write()`:
    - If `translate_config and translate_config.enabled`: call `translate_markdown(markdown, translate_config)`
    - Update `markdown` with result, log translation outcome
  - _Requirements: 1.1, 4.2, 5.1, 5.3_

- [x] 5.3 Checkpoint — CLI integration works end-to-end
  - Run `meeting-export fathom sync --translate --dry-run` (verify no crashes, flag accepted)
  - Run `meeting-export gmeet sync --translate --dry-run` (verify no crashes, flag accepted)
  - Run `pytest tests/` to ensure no regressions
  - _Requirements: all_

## 6. Configuration

- [x] 6.1 Update `.env.example` with translation-related variables
  - Add `ANTHROPIC_API_KEY=`, `ANTHROPIC_BASE_URL=` (optional, for AI gateway)
  - _Requirements: 6.3, 6.4, 6.5_

- [x] 6.2 Final Checkpoint — All tests pass, full integration verified
  - Run complete test suite: `pytest tests/`
  - Verify all requirements are covered by tasks
  - _Requirements: all_
