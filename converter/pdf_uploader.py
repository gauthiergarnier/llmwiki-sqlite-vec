"""Uploads an Office file's PDF rendition to a presigned S3 URL so the app can display it."""

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

UPLOAD_CHUNK_BYTES = 256 * 1024


class PdfUploader:
    async def upload(self, url: str, pdf_path: Path, request_id: str) -> None:
        """PUT the PDF; a failed upload fails the job so the document isn't marked ready without a viewable file."""
        host = urlparse(url).hostname
        headers = {"Content-Type": "application/pdf", "Content-Length": str(pdf_path.stat().st_size)}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
                resp = await client.put(url, content=self._chunks(pdf_path), headers=headers)
                resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error("pdf rendition upload failed: %s host=%s request_id=%s", type(e).__name__, host, request_id)
            raise HTTPException(502, "Could not store the PDF preview") from e

    @staticmethod
    async def _chunks(pdf_path: Path) -> AsyncIterator[bytes]:
        with pdf_path.open("rb") as f:
            while chunk := f.read(UPLOAD_CHUNK_BYTES):
                yield chunk
