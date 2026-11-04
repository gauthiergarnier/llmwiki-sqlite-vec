"""Fork: API-side citation parser (api/services/references.py) — used by graph rebuild + reindex."""

import pytest
from services.references import _CITATION_RE, parse_citation_filename

from tests.support.citation_cases import FILENAME_CASES, NEWLINE_CONTENT, NEWLINE_TARGETS


@pytest.mark.parametrize(("raw", "expected"), FILENAME_CASES)
def test_parse_citation_filename(raw, expected):
    assert parse_citation_filename(raw) == expected


def test_citation_regex_does_not_cross_lines():
    assert _CITATION_RE.findall(NEWLINE_CONTENT) == NEWLINE_TARGETS
