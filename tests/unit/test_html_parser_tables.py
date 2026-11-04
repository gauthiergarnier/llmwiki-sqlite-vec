import time

import pytest
from html_parser.parser import Parser


def _parse_seconds(html: str) -> tuple[float, str]:
    start = time.monotonic()
    content = Parser(html, content_only=True).parse().content
    return time.monotonic() - start, content


@pytest.mark.parametrize("html", [
    '<table><tr><td rowspan="999999999" colspan="999999999">x</td></tr></table>',
    "<table>" + '<tr><td colspan="2000000">x</td><td>y</td></tr>' * 20 + "</table>",
    "<table>" + "<tr>" + '<td rowspan="65534" colspan="1000">x</td>' * 50 + "</tr>" * 200 + "</table>",
])
def test_hostile_spans_parse_quickly(html: str) -> None:
    seconds, content = _parse_seconds(html)
    assert seconds < 2
    assert "x" in content


def test_ordinary_spans_still_render() -> None:
    html = (
        "<table>"
        "<tr><th>Name</th><th colspan='2'>Scores</th></tr>"
        "<tr><td rowspan='2'>Ada</td><td>1</td><td>2</td></tr>"
        "<tr><td>3</td><td>4</td></tr>"
        "</table>"
    )
    _, content = _parse_seconds(html)
    assert "| Name | Scores |  |" in content
    assert "| Ada | 1 | 2 |" in content
    assert "|  | 3 | 4 |" in content
