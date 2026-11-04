"""Streams source files from S3 to disk under a byte cap."""

import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class SourceDownloader:
    def __init__(self, max_bytes: int) -> None:
        self._max_bytes = max_bytes

    async def download(self, url: str, dest: Path, request_id: str) -> None:
        host = urlparse(url).hostname
        try:
            async with (
                httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client,
                client.stream("GET", url) as resp,
            ):
                resp.raise_for_status()
                await self._write_bounded(resp, dest)
        except httpx.HTTPStatusError as e:
            logger.error("source download rejected: status=%s host=%s request_id=%s",
                         e.response.status_code, host, request_id)
            raise HTTPException(502, f"Could not fetch source (HTTP {e.response.status_code})") from e
        except httpx.HTTPError as e:
            logger.error("source download error: %s host=%s request_id=%s",
                         type(e).__name__, host, request_id)
            raise HTTPException(502, "Could not fetch source file") from e

    async def _write_bounded(self, resp: httpx.Response, dest: Path) -> None:
        total = 0
        with open(dest, "wb") as f:
            async for chunk in resp.aiter_bytes(64 * 1024):
                total += len(chunk)
                if total > self._max_bytes:
                    raise HTTPException(413, f"Source file exceeds {self._max_bytes} bytes")
                f.write(chunk)
