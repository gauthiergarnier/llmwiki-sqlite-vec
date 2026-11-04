import importlib.util
from pathlib import Path


def _references_module():
    spec = importlib.util.spec_from_file_location(
        "api_references_test",
        Path(__file__).resolve().parents[2] / "api" / "services" / "references.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_citation_preserves_hyphenated_version_suffix():
    parse_citation_filename = _references_module().parse_citation_filename
    assert parse_citation_filename("2501.12948v2-2.pdf, p.5") == (
        "2501.12948v2-2.pdf",
        5,
    )


def test_parse_citation_markdown_link_keeps_page_suffix():
    parse_citation_filename = _references_module().parse_citation_filename
    assert parse_citation_filename("[paper.pdf](https://example.com/paper), p.7") == (
        "paper.pdf",
        7,
    )


def test_extract_references_matches_hyphenated_version_source():
    extract_references = _references_module().extract_references
    source = {
        "id": "source-1",
        "filename": "2501.12948v2-2.pdf",
        "path": "/",
        "title": "DeepSeek-R1",
    }
    page = {
        "id": "page-1",
        "filename": "deepseek-r1.md",
        "path": "/wiki/",
        "title": "DeepSeek-R1",
    }

    edges = extract_references(
        "DeepSeek-R1 uses reinforcement learning.[^1]\n\n[^1]: 2501.12948v2-2.pdf, p.5",
        "page-1",
        "",
        {"2501.12948v2-2.pdf": source, "deepseek-r1.md": page},
        {"2501.12948v2-2": source, "deepseek-r1": page},
        {"deepseek-r1.md": page},
    )

    assert edges == [{"target_id": "source-1", "type": "cites", "page": 5}]


def test_named_footnotes_become_citation_edges():
    module = _references_module()
    paper = {"id": "paper-id"}
    content = "Claim.[^smith2020]\n\n[^smith2020]: paper.pdf, p.3\n[^1]: paper.pdf, p.4"

    edges = module.extract_references(content, "page-id", "/wiki/", {"paper.pdf": paper}, {}, {})

    assert edges == [{"target_id": "paper-id", "type": "cites", "page": 3}]
