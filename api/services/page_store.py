"""Persists extraction results: pages, chunks, assets, and document status."""

import base64
import json
import logging

import asyncpg
from config import settings
from services.bulk_persistence import insert_assets, insert_pages
from services.chunker import chunk_pages, store_chunks
from services.extracted_assets import ExtractedAsset, build_pdf_image_assets
from services.page_quota import PageQuota
from services.s3 import S3Service

logger = logging.getLogger(__name__)


class PageStore:
    def __init__(self, pool: asyncpg.Pool, s3: S3Service, quota: PageQuota) -> None:
        self._pool = pool
        self._s3 = s3
        self._quota = quota

    async def store_extracted_pages(
        self, document_id: str, user_id: str, kb_id: str,
        page_contents: list[tuple[int, str]], parser: str,
        page_elements: dict[int, dict] | None = None,
        assets: list[ExtractedAsset] | None = None,
    ) -> None:
        num_pages = len(page_contents)
        self._check_page_cap(num_pages)

        full_content = "\n\n---\n\n".join(md for _, md in page_contents)
        chunks = chunk_pages(page_contents)
        page_rows = [(num, md, (page_elements or {}).get(num)) for num, md in page_contents]

        await self._replace_document_pages(
            document_id, user_id, kb_id, num_pages, full_content, parser, page_rows, assets or [],
        )
        await store_chunks(self._pool, document_id, user_id, kb_id, chunks)
        logger.info("Extracted (%s): doc=%s pages=%d chunks=%d", parser, document_id[:8], num_pages, len(chunks))

    async def store_mistral_result(
        self, document_id: str, user_id: str, kb_id: str, ocr_result: dict,
    ) -> None:
        await self._upload_raw_ocr_json(document_id, user_id, ocr_result)

        pages = ocr_result.get("pages", [])
        self._check_page_cap(len(pages))

        pages_with_images = self._mistral_pages_with_images(pages)
        assets, page_elements = await self.build_pdf_assets(document_id, pages_with_images)

        full_content = "\n\n---\n\n".join(page.get("markdown", "") for page in pages)
        page_contents = [(page.get("index", 0) + 1, page.get("markdown", "")) for page in pages]
        chunks = chunk_pages(page_contents)
        page_rows = self._mistral_page_rows(pages, page_elements)

        await self._replace_document_pages(
            document_id, user_id, kb_id, len(pages), full_content, "mistral", page_rows, assets,
        )
        await self.upload_assets(user_id, assets)
        await store_chunks(self._pool, document_id, user_id, kb_id, chunks)
        logger.info("OCR complete: doc=%s pages=%d chunks=%d", document_id[:8], len(pages), len(chunks))

    async def store_html(self, document_id: str, user_id: str, kb_id: str, content: str, chunks: list) -> None:
        conn = await self._pool.acquire()
        try:
            async with conn.transaction():
                await self._quota.check_user_page_limit(user_id, 1, conn=conn)
                await self._update_html_document(conn, document_id, content)
        finally:
            await self._pool.release(conn)

        await store_chunks(self._pool, document_id, user_id, kb_id, chunks)
        logger.info("HTML processed: doc=%s chunks=%d", document_id[:8], len(chunks))

    async def mark_image_ready(self, document_id: str, user_id: str) -> None:
        conn = await self._pool.acquire()
        try:
            async with conn.transaction():
                await self._quota.check_user_page_limit(user_id, 1, conn=conn)
                await self._update_image_document(conn, document_id)
        finally:
            await self._pool.release(conn)
        logger.info("Image stored: doc=%s", document_id[:8])

    async def store_sheets(
        self, document_id: str, user_id: str, kb_id: str, sheets: list[tuple[str, str]],
    ) -> None:
        full_content = "\n\n---\n\n".join(f"## {name}\n\n{md}" for name, md in sheets)
        page_contents = [(i + 1, md) for i, (_, md) in enumerate(sheets)]
        chunks = chunk_pages(page_contents)
        page_rows = [(i, md, {"sheet_name": name}) for i, (name, md) in enumerate(sheets, 1)]

        conn = await self._pool.acquire()
        try:
            async with conn.transaction():
                await self._quota.check_user_page_limit(user_id, len(sheets), conn=conn)
                await self._delete_document_pages(conn, document_id)
                await insert_pages(conn, document_id, page_rows)
                await self._update_sheet_document(conn, document_id, full_content, len(sheets))
        finally:
            await self._pool.release(conn)

        await store_chunks(self._pool, document_id, user_id, kb_id, chunks)
        logger.info("Spreadsheet processed: doc=%s sheets=%d chunks=%d", document_id[:8], len(sheets), len(chunks))

    async def build_pdf_assets(
        self, document_id: str, pages_with_images: list[tuple[int, str, list[dict]]],
    ) -> tuple[list[ExtractedAsset], dict[int, dict]]:
        doc = await self._fetch_document_identity(document_id)
        if not doc:
            return [], {}
        return build_pdf_image_assets(document_id, doc["filename"], doc["path"], pages_with_images)

    async def upload_assets(self, user_id: str, assets: list[ExtractedAsset]) -> None:
        for asset in assets:
            await self._s3.upload_bytes(
                f"{user_id}/{asset.document_id}/source.{asset.file_type}",
                asset.data,
                asset.content_type,
            )

    async def set_status(self, document_id: str, status: str) -> None:
        await self._pool.execute(
            "UPDATE documents SET status = $2, updated_at = now() WHERE id = $1",
            document_id, status,
        )

    @staticmethod
    def _check_page_cap(num_pages: int) -> None:
        if num_pages > settings.QUOTA_MAX_PAGES_PER_DOC:
            raise ValueError(
                f"Document has {num_pages} pages, maximum is {settings.QUOTA_MAX_PAGES_PER_DOC}."
            )

    async def _replace_document_pages(
        self, document_id: str, user_id: str, kb_id: str, page_count: int,
        full_content: str, parser: str, page_rows: list[tuple[int, str, dict | None]],
        assets: list[ExtractedAsset],
    ) -> None:
        """Quota check + all page/asset writes in one transaction under the user's advisory lock."""
        metadata_patch = (
            json.dumps({"assets": [asset.metadata() for asset in assets]})
            if assets else None
        )
        conn = await self._pool.acquire()
        try:
            async with conn.transaction():
                await self._quota.check_user_page_limit(user_id, page_count, conn=conn)
                await self._delete_document_pages(conn, document_id)
                await self._delete_pdf_image_children(conn, user_id, document_id)
                await insert_pages(conn, document_id, page_rows)
                await insert_assets(conn, kb_id, user_id, assets)
                await self._update_extracted_document(
                    conn, document_id, full_content, page_count, parser, metadata_patch,
                )
        finally:
            await self._pool.release(conn)

    async def _upload_raw_ocr_json(self, document_id: str, user_id: str, ocr_result: dict) -> None:
        await self._s3.upload_bytes(
            f"{user_id}/{document_id}/ocr.json",
            json.dumps(ocr_result).encode(),
            "application/json",
        )

    @staticmethod
    def _mistral_pages_with_images(pages: list[dict]) -> list[tuple[int, str, list[dict]]]:
        pages_with_images = []
        for page in pages:
            page_num = page.get("index", 0) + 1
            extracted_images = []
            for img in page.get("images", []):
                img_id = img.get("id")
                img_b64 = img.get("image_base64")
                if not img_id or not img_b64:
                    continue
                if img_b64.startswith("data:"):
                    img_b64 = img_b64.split(",", 1)[1]
                extracted_images.append({
                    "id": img_id,
                    "bytes": base64.b64decode(img_b64),
                    "format": "jpg",
                })
            pages_with_images.append((page_num, page.get("markdown", ""), extracted_images))
        return pages_with_images

    @staticmethod
    def _mistral_page_rows(
        pages: list[dict], page_elements: dict[int, dict],
    ) -> list[tuple[int, str, dict | None]]:
        page_rows: list[tuple[int, str, dict | None]] = []
        for page in pages:
            page_index = page.get("index", 0) + 1
            elements = {}
            page_assets = page_elements.get(page_index, {}).get("images")
            if page_assets:
                elements["images"] = page_assets
            if page.get("dimensions"):
                elements["dimensions"] = page["dimensions"]
            if page.get("tables"):
                elements["tables"] = page["tables"]
            page_rows.append((page_index, page.get("markdown", ""), elements or None))
        return page_rows

    @staticmethod
    async def _delete_document_pages(conn: asyncpg.Connection, document_id: str) -> None:
        await conn.execute("DELETE FROM document_pages WHERE document_id = $1", document_id)

    @staticmethod
    async def _delete_pdf_image_children(conn: asyncpg.Connection, user_id: str, document_id: str) -> None:
        await conn.execute(
            "DELETE FROM documents WHERE user_id = $1 "
            "AND metadata->>'parent_document_id' = $2 "
            "AND metadata->>'kind' = 'pdf_image'",
            user_id, document_id,
        )

    @staticmethod
    async def _update_extracted_document(
        conn: asyncpg.Connection, document_id: str, content: str,
        page_count: int, parser: str, metadata_patch: str | None,
    ) -> None:
        await conn.execute(
            "UPDATE documents SET status = 'ready', content = $2, page_count = $3, "
            "parser = $4, metadata = CASE WHEN $5::jsonb IS NULL THEN metadata "
            "ELSE COALESCE(metadata, '{}'::jsonb) || $5::jsonb END, "
            "updated_at = now() WHERE id = $1",
            document_id, content, page_count, parser, metadata_patch,
        )

    @staticmethod
    async def _update_html_document(conn: asyncpg.Connection, document_id: str, content: str) -> None:
        await conn.execute(
            "UPDATE documents SET status = 'ready', content = $2, page_count = 1, parser = 'webmd', updated_at = now() "
            "WHERE id = $1",
            document_id, content,
        )

    @staticmethod
    async def _update_image_document(conn: asyncpg.Connection, document_id: str) -> None:
        await conn.execute(
            "UPDATE documents SET status = 'ready', page_count = 1, parser = 'native', updated_at = now() "
            "WHERE id = $1",
            document_id,
        )

    @staticmethod
    async def _update_sheet_document(
        conn: asyncpg.Connection, document_id: str, content: str, page_count: int,
    ) -> None:
        await conn.execute(
            "UPDATE documents SET status = 'ready', content = $2, page_count = $3, parser = 'openpyxl', updated_at = now() "
            "WHERE id = $1",
            document_id, content, page_count,
        )

    async def _fetch_document_identity(self, document_id: str) -> asyncpg.Record | None:
        return await self._pool.fetchrow(
            "SELECT filename, path FROM documents WHERE id = $1",
            document_id,
        )
