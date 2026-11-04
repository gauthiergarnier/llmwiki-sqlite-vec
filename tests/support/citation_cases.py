"""Fork: shared cases for the two footnote-citation parsers (api/ and mcp/ copies)."""

# (raw footnote target, expected (filename, page))
FILENAME_CASES = [
    ("paper.pdf, p.3", ("paper.pdf", 3)),
    ("paper.pdf", ("paper.pdf", None)),
    ("[paper.pdf](http://example.com), p.7", ("paper.pdf", 7)),
    ("paper.pdf, p.5 — section on scaling", ("paper.pdf", 5)),
    # Date-prefixed transcripts: upstream cut these at the first " - ".
    ("2026-06-23 - Meeting Notes.md", ("2026-06-23 - Meeting Notes.md", None)),
    ("2026-05-28 - Fabian  Gauthier - Shopware prep call.md", ("2026-05-28 - Fabian  Gauthier - Shopware prep call.md", None)),
    ("[2026-06-23 - A - B.md](../A/2026-06-23%20-%20A%20-%20B.md) — kickoff", ("2026-06-23 - A - B.md", None)),
    ("**2026-04-27 - Summary — Upsun × IBM.md**", ("2026-04-27 - Summary — Upsun × IBM.md", None)),
    ("notes.md (source)", ("notes.md", None)),
    # No extension: fall back to cutting at the first separator.
    ("Some Doc - annotation", ("Some Doc", None)),
    ("Some Doc, §2", ("Some Doc", None)),
]

# Inline footnote references (mid-line, or ending a line before a colon) are not definitions.
NEWLINE_CONTENT = (
    "Escalated to engineering[^b27]: **incorrect GLs** on voided-invoice.pdf\n"
    "**Mechanics agreed**[^smurfit]:\n"
    "```mermaid\n"
    "[^1]: 2026-06-23 - Meeting Notes.md\n"
    "[^a2]:\tdeck.pdf, p.4\n"
)
NEWLINE_TARGETS = ["2026-06-23 - Meeting Notes.md", "deck.pdf, p.4"]
