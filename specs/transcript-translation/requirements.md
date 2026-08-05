# Requirements: Transcript Translation

Meeting transcripts exported by the meeting-export CLI (from Fathom and Google Meet connectors) are sometimes recorded in languages other than English. The organization uses French and German as primary working languages, and Spanish as a secondary language. This feature adds automatic language detection and translation to English in the meeting-export pipeline, so that all transcripts land in the Obsidian vault in English — ready for search and consumption in LLM Wiki.

## Glossary

- **Connector**: A source-specific module in meeting-export that fetches meeting data (Fathom or GMeet)
- **Transcript_Content**: The text body of a meeting export — summary, action items, transcript sections — excluding YAML frontmatter
- **Source_Language**: The detected original language of the Transcript_Content (fr, de, or es)
- **Translation_Backend**: The service used to translate text (default: Claude API)
- **Translated_Output**: The English version of a Transcript_Content produced by the Translation_Backend
- **Language_Detector**: The component that identifies the language of Transcript_Content before translation

## Requirements

### Requirement 1: Automatic Translation of Non-English Transcripts

**As a** knowledge base user,
**I want** meeting transcripts in French, German, or Spanish to be automatically translated to English during export,
**so that** all meeting content in the Obsidian vault is searchable and readable in English.

#### Acceptance Criteria

1. WHEN a Connector produces Transcript_Content AND the Language_Detector identifies the Source_Language as French (fr), German (de), or Spanish (es), THE meeting-export CLI SHALL translate the Transcript_Content to English before writing the markdown file
2. WHEN the Language_Detector identifies the Transcript_Content as English, THE meeting-export CLI SHALL write the file as-is without invoking the Translation_Backend
3. WHEN the Transcript_Content contains a mix of English and a supported Source_Language (e.g., a meeting that starts in English and switches to French mid-way), THE meeting-export CLI SHALL translate the entire content to produce a consistent English output

### Requirement 2: Preserve Original Language Metadata

**As a** knowledge base user,
**I want** translated files to indicate they were translated and from which language,
**so that** I know when I'm reading a translation and can assess context accordingly.

#### Acceptance Criteria

1. WHEN the meeting-export CLI translates a Transcript_Content, THE output markdown file SHALL include `original_language: <Source_Language>` and `translated: true` fields in the YAML frontmatter
2. WHEN a Transcript_Content is already in English, THE output markdown file SHALL NOT include translation-related frontmatter fields
3. WHEN the meeting-export CLI translates a Transcript_Content, THE output markdown file SHALL include a note below the frontmatter indicating: "Auto-translated from [Source_Language]"

### Requirement 3: Language Detection Reliability

**As a** user,
**I want** language detection to be accurate,
**so that** English transcripts are not unnecessarily translated and non-English transcripts are correctly identified.

#### Acceptance Criteria

1. THE Language_Detector SHALL detect French (fr), German (de), Spanish (es), and English (en) from the Transcript_Content
2. WHEN the Language_Detector cannot determine the language with sufficient confidence, THE meeting-export CLI SHALL skip translation and export the content unchanged
3. IF the Transcript_Content is in an unsupported language (not fr, de, es, or en), THEN THE meeting-export CLI SHALL export the content unchanged and log a warning with the detected language code
4. THE Language_Detector SHALL sample multiple sections of the Transcript_Content (beginning, middle, end) to detect mid-meeting language switches — not just the first N characters

### Requirement 3b: Mid-Meeting Language Switches

**As a** user whose meetings switch languages partway through (e.g., Google Meet auto-detect picks up a language change),
**I want** the translation to handle mixed-language transcripts correctly,
**so that** the full meeting is readable in English even when the original recording changed language mid-way.

#### Acceptance Criteria

1. WHEN the Language_Detector detects that only a portion of the Transcript_Content is in a non-English supported language, THE meeting-export CLI SHALL still translate the full content to produce a consistent English output
2. WHEN a Transcript contains segments in multiple supported languages (e.g., French then German), THE meeting-export CLI SHALL translate all non-English segments to English in a single translation pass
3. THE Language_Detector SHALL flag a transcript as needing translation if any significant section (>10% of body text) is in a supported non-English language, even if the majority is English

### Requirement 4: Translation Applies to Both Connectors

**As a** user exporting from Fathom and Google Meet,
**I want** translation to work consistently across both connectors,
**so that** all meeting sources receive the same treatment.

#### Acceptance Criteria

1. WHEN the Fathom Connector produces a meeting export, THE translation step SHALL process the summary, action items, and transcript sections
2. WHEN the GMeet Connector produces a meeting export (Gemini notes or manual notes), THE translation step SHALL process all content sections
3. THE translation step SHALL preserve markdown formatting, speaker names, timestamps, and structural elements (headings, bullet points, block anchors) in the Translated_Output

### Requirement 5: Translation Error Handling

**As a** user,
**I want** the export to succeed even when translation fails,
**so that** I always get my meeting content — untranslated if necessary.

#### Acceptance Criteria

1. IF the Translation_Backend fails (API error, timeout, rate limit), THEN THE meeting-export CLI SHALL write the original untranslated content to the vault and log a warning
2. IF the Translation_Backend fails, THEN THE output file SHALL include `translated: false` and `translation_error: "<reason>"` in the YAML frontmatter
3. WHEN translation fails, THE meeting-export CLI SHALL continue processing remaining meetings without aborting the sync

### Requirement 6: Translation Configuration

**As a** system administrator,
**I want** to configure the translation backend and behavior,
**so that** I can control costs and choose the translation provider.

#### Acceptance Criteria

1. THE meeting-export CLI SHALL support a `--translate` flag on sync commands to enable translation (disabled by default)
2. THE meeting-export CLI SHALL use the Anthropic Python SDK to call the Claude API as the Translation_Backend
3. WHERE the `ANTHROPIC_BASE_URL` environment variable is set, THE meeting-export CLI SHALL route all Claude API calls through the specified AI gateway URL (e.g., a corporate proxy or custom gateway)
4. WHERE `ANTHROPIC_BASE_URL` is not set, THE meeting-export CLI SHALL call the Anthropic API directly using the standard SDK defaults
5. WHERE the `ANTHROPIC_API_KEY` environment variable is set AND `--translate` is enabled, THE meeting-export CLI SHALL authenticate using that API key
6. WHEN `--translate` is enabled but `ANTHROPIC_API_KEY` is not set, THE meeting-export CLI SHALL exit with a clear error message
