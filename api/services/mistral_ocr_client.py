"""HTTP client for the Mistral OCR API."""

import asyncio
import logging

import httpx
from config import settings

logger = logging.getLogger(__name__)


class MistralOcrClient:
    OCR_URL = "https://api.mistral.ai/v1/ocr"
    MAX_RETRIES = 3
    RETRY_BACKOFF = [2, 5, 10]

    async def ocr(self, url: str, url_type: str = "document_url") -> dict:
        last_error: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            try:
                return await self._post_ocr(url, url_type)
            except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
                last_error = e
                if attempt < self.MAX_RETRIES - 1:
                    wait = self.RETRY_BACKOFF[attempt]
                    logger.warning("Mistral OCR attempt %d failed: %s, retrying in %ds", attempt + 1, e, wait)
                    await asyncio.sleep(wait)
        raise last_error or RuntimeError("Mistral OCR failed after retries")

    async def _post_ocr(self, url: str, url_type: str) -> dict:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            resp = await client.post(
                self.OCR_URL,
                headers={
                    "Authorization": f"Bearer {settings.MISTRAL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "mistral-ocr-latest",
                    "document": {"type": url_type, url_type: url},
                    "include_image_base64": True,
                    "table_format": "markdown",
                },
            )
            resp.raise_for_status()
            return resp.json()
