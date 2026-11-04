"""Private knowledge-base activity capture and API behavior."""

import json

import asyncpg
import pytest

from tests.helpers.jwt import auth_headers

USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_USER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.fixture(autouse=True)
async def seed_users(pool):
    await pool.execute("TRUNCATE users CASCADE")
    await pool.executemany(
        "INSERT INTO users (id, email, display_name) VALUES ($1, $2, $3)",
        [
            (USER_ID, "owner@test.com", "Owner"),
            (OTHER_USER_ID, "other@test.com", "Other"),
        ],
    )


async def create_wiki(client, name: str = "Activity Wiki") -> str:
    response = await client.post(
        "/v1/knowledge-bases",
        headers=auth_headers(USER_ID),
        json={"name": name},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def event_rows(pool, kb_id: str):
    return await pool.fetch(
        "SELECT event_type, subject_kind, subject_title, subject_path, metadata "
        "FROM knowledge_base_events WHERE knowledge_base_id = $1 ORDER BY id",
        kb_id,
    )


class TestActivityCapture:

    async def test_wiki_creation_is_one_visible_event(self, client, pool):
        kb_id = await create_wiki(client)

        rows = await event_rows(pool, kb_id)
        assert [row["event_type"] for row in rows] == ["wiki.created"]
        assert rows[0]["subject_title"] == "Activity Wiki"

        docs = await pool.fetch(
            "SELECT filename FROM documents WHERE knowledge_base_id = $1",
            kb_id,
        )
        assert [row["filename"] for row in docs] == ["overview.md"]

    async def test_page_mutations_are_semantic_and_noise_is_ignored(self, client, pool):
        kb_id = await create_wiki(client)
        headers = auth_headers(USER_ID)
        created = await client.post(
            f"/v1/knowledge-bases/{kb_id}/documents/note",
            headers=headers,
            json={
                "filename": "retrieval.md",
                "path": "/wiki/",
                "content": "---\ntitle: Retrieval\ntags: [search]\n---\n\nFirst draft.",
            },
        )
        assert created.status_code == 201
        doc_id = created.json()["id"]

        changed = await client.put(
            f"/v1/documents/{doc_id}/content",
            headers=headers,
            json={"content": "Second draft."},
        )
        assert changed.status_code == 200
        unchanged = await client.put(
            f"/v1/documents/{doc_id}/content",
            headers=headers,
            json={"content": "Second draft."},
        )
        assert unchanged.status_code == 200

        await pool.execute(
            "UPDATE documents SET highlights = $1::jsonb, updated_at = now() WHERE id = $2",
            json.dumps([{"id": "h1", "text": "Second"}]),
            doc_id,
        )

        renamed = await client.patch(
            f"/v1/documents/{doc_id}",
            headers=headers,
            json={"title": "Retrieval design"},
        )
        assert renamed.status_code == 200

        rows = await event_rows(pool, kb_id)
        assert [row["event_type"] for row in rows] == [
            "wiki.created",
            "page.created",
            "page.updated",
            "page.updated",
        ]
        assert json.loads(rows[2]["metadata"])["changes"] == ["content"]
        assert json.loads(rows[3]["metadata"])["changes"] == ["title"]

    async def test_source_extraction_hidden_assets_and_deletion(self, client, pool):
        kb_id = await create_wiki(client)
        source_id = await pool.fetchval(
            "INSERT INTO documents (knowledge_base_id, user_id, filename, title, path, "
            "file_type, status, content, metadata) "
            "VALUES ($1, $2, 'paper.pdf', 'Paper', '/', 'pdf', 'pending', NULL, '{}'::jsonb) "
            "RETURNING id",
            kb_id,
            USER_ID,
        )
        await pool.execute(
            "UPDATE documents SET content = 'Extracted', status = 'ready', updated_at = now() "
            "WHERE id = $1",
            source_id,
        )
        await pool.execute(
            "INSERT INTO documents (knowledge_base_id, user_id, filename, title, path, "
            "file_type, status, metadata) "
            "VALUES ($1, $2, 'asset.png', 'Asset', '/paper.assets/', 'png', 'ready', "
            "'{\"hidden\": true, \"asset\": true}'::jsonb)",
            kb_id,
            USER_ID,
        )
        await pool.execute("DELETE FROM documents WHERE id = $1", source_id)

        rows = await event_rows(pool, kb_id)
        assert [row["event_type"] for row in rows] == [
            "wiki.created",
            "source.added",
            "source.deleted",
        ]
        assert rows[-1]["subject_title"] == "Paper"
        assert rows[-1]["subject_path"] == "/paper.pdf"

    async def test_page_archive_restore_and_transaction_rollback(self, client, pool):
        kb_id = await create_wiki(client)
        headers = auth_headers(USER_ID)
        created = await client.post(
            f"/v1/knowledge-bases/{kb_id}/documents/note",
            headers=headers,
            json={"filename": "durable.md", "path": "/wiki/", "content": "Keep me."},
        )
        doc_id = created.json()["id"]

        archived = await client.delete(f"/v1/documents/{doc_id}", headers=headers)
        assert archived.status_code == 204
        await pool.execute(
            "UPDATE documents SET archived = false, updated_at = now() WHERE id = $1",
            doc_id,
        )

        before = await pool.fetchval(
            "SELECT count(*) FROM knowledge_base_events WHERE knowledge_base_id = $1",
            kb_id,
        )
        async with pool.acquire() as connection:
            transaction = connection.transaction()
            await transaction.start()
            await connection.execute(
                "INSERT INTO documents (knowledge_base_id, user_id, filename, title, path, "
                "file_type, status, content) VALUES ($1, $2, 'rolled-back.md', 'Rolled back', "
                "'/wiki/', 'md', 'ready', '')",
                kb_id,
                USER_ID,
            )
            await transaction.rollback()

        assert await pool.fetchval(
            "SELECT count(*) FROM knowledge_base_events WHERE knowledge_base_id = $1",
            kb_id,
        ) == before
        rows = await event_rows(pool, kb_id)
        assert [row["event_type"] for row in rows] == [
            "wiki.created",
            "page.created",
            "page.archived",
            "page.restored",
        ]
        assert rows[-2]["subject_path"] == "/wiki/durable.md"


class TestActivityAPI:

    async def test_feed_is_owner_only_and_cursor_paginated(self, client, pool):
        kb_id = await create_wiki(client)
        for filename in ("one.md", "two.md", "three.md"):
            await pool.execute(
                "INSERT INTO documents (knowledge_base_id, user_id, filename, title, path, "
                "file_type, status, content) VALUES ($1, $2, $3, $3, '/wiki/', 'md', 'ready', '')",
                kb_id,
                USER_ID,
                filename,
            )

        first = await client.get(
            f"/v1/knowledge-bases/{kb_id}/events?limit=2",
            headers=auth_headers(USER_ID),
        )
        assert first.status_code == 200
        first_page = first.json()
        assert len(first_page["items"]) == 2
        assert first_page["next_cursor"] == first_page["items"][-1]["id"]

        second = await client.get(
            f"/v1/knowledge-bases/{kb_id}/events?limit=2&before={first_page['next_cursor']}",
            headers=auth_headers(USER_ID),
        )
        assert second.status_code == 200
        second_page = second.json()
        assert len(second_page["items"]) == 2
        assert {
            item["id"] for item in first_page["items"]
        }.isdisjoint(item["id"] for item in second_page["items"])
        assert all(isinstance(item["id"], str) for item in first_page["items"])

        forbidden = await client.get(
            f"/v1/knowledge-bases/{kb_id}/events",
            headers=auth_headers(OTHER_USER_ID),
        )
        assert forbidden.status_code == 404

    async def test_rls_allows_only_owner_reads_and_no_client_writes(self, client, pool):
        kb_id = await create_wiki(client)

        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SET LOCAL ROLE authenticated")
                await connection.execute(
                    "SELECT set_config('request.jwt.claims', $1, true)",
                    json.dumps({"sub": OTHER_USER_ID}),
                )
                assert await connection.fetchval(
                    "SELECT count(*) FROM knowledge_base_events WHERE knowledge_base_id = $1",
                    kb_id,
                ) == 0

            async with connection.transaction():
                await connection.execute("SET LOCAL ROLE authenticated")
                await connection.execute(
                    "SELECT set_config('request.jwt.claims', $1, true)",
                    json.dumps({"sub": USER_ID}),
                )
                assert await connection.fetchval(
                    "SELECT count(*) FROM knowledge_base_events WHERE knowledge_base_id = $1",
                    kb_id,
                ) == 1
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    await connection.execute(
                        "UPDATE knowledge_base_events SET subject_title = 'tampered' "
                        "WHERE knowledge_base_id = $1",
                        kb_id,
                    )
