from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routes import files


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    (tmp_path / ".llmwiki" / "cache" / "local" / "doc").mkdir(parents=True)
    (tmp_path / ".llmwiki" / "index.db").write_bytes(b"SQLite format 3\x00secret")
    (tmp_path / ".llmwiki" / "cache" / "local" / "doc" / "tagged.html").write_text("<p>cached</p>")
    (tmp_path / ".env").write_text("TOKEN=secret")
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources" / "paper.txt").write_bytes(b"0123456789")
    (tmp_path / "sources" / "page.html").write_text("<script>alert(1)</script>")
    files.set_workspace_root(str(tmp_path))
    app = FastAPI()
    app.include_router(files.router)
    return TestClient(app)


@pytest.mark.parametrize("key", [".llmwiki/index.db", "sources/../.llmwiki/index.db", ".env", "../etc/passwd"])
def test_hidden_and_escaping_paths_are_not_served(client: TestClient, key: str) -> None:
    assert client.get(f"/v1/files/{key}").status_code == 404


def test_cache_artifacts_are_still_served(client: TestClient) -> None:
    resp = client.get("/v1/files/local/doc/tagged.html")
    assert resp.status_code == 200
    assert resp.text == "<p>cached</p>"


def test_active_content_is_sandboxed(client: TestClient) -> None:
    resp = client.get("/v1/files/sources/page.html")
    assert resp.headers["content-security-policy"] == "sandbox"
    assert "content-security-policy" not in client.get("/v1/files/sources/paper.txt").headers


def test_suffix_range_returns_the_tail(client: TestClient) -> None:
    resp = client.get("/v1/files/sources/paper.txt", headers={"Range": "bytes=-3"})
    assert resp.status_code == 206
    assert resp.content == b"789"


def test_malformed_range_is_rejected_not_500(client: TestClient) -> None:
    assert client.get("/v1/files/sources/paper.txt", headers={"Range": "bytes=abc"}).status_code in (400, 416)


def test_etag_round_trip_returns_304(client: TestClient) -> None:
    etag = client.get("/v1/files/sources/paper.txt").headers["etag"]
    assert client.get("/v1/files/sources/paper.txt", headers={"If-None-Match": etag}).status_code == 304
