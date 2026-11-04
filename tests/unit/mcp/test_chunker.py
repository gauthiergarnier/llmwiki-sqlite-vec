"""The MCP chunker must keep short content and label chunks with their own section."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "mcp"))


def test_short_note_produces_a_chunk():
    from vaultfs.chunker import chunk_text
    assert [c.content for c in chunk_text("# Q3 Revenue\n\n- Up 20% YoY")] == ["# Q3 Revenue\n\n- Up 20% YoY"]


def test_breadcrumb_names_the_section_the_chunk_came_from():
    from vaultfs.chunker import chunk_text
    text = "# Alpha\n\n" + ("alpha text " * 400) + "\n\n# Beta\n\n" + ("beta text " * 50)
    chunks = chunk_text(text)
    assert chunks[0].header_breadcrumb == "Alpha"
    assert chunks[-1].header_breadcrumb == "Beta"
