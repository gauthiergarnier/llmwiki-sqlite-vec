"""Fork: MCP-side citation parser (mcp/tools/references.py) — must match the API copy."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "mcp"))
from tests.support.citation_cases import FILENAME_CASES, NEWLINE_CONTENT, NEWLINE_TARGETS  # noqa: E402


@pytest.mark.parametrize(("raw", "expected"), FILENAME_CASES)
def test_parse_citation_filename(raw, expected):
    from tools.references import _parse_citation_filename

    assert _parse_citation_filename(raw) == expected


def test_citation_regex_does_not_cross_lines():
    from tools.references import _CITATION_RE

    assert _CITATION_RE.findall(NEWLINE_CONTENT) == NEWLINE_TARGETS
