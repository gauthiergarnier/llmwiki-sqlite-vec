"""Minimal Ollama client (stdlib only — no extra dependency).

Used off the hot path by the background consolidation job and, when enabled,
by the ConflictAssessor. Degrades gracefully: returns None if Ollama is
unreachable, so callers fall back to embedding-only heuristics.
"""

import asyncio
import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


async def ollama_chat(
    messages: list[dict], *, model: str, url: str, timeout: float, json_mode: bool = True,
) -> str | None:
    """Call Ollama's /api/chat. Returns the assistant message content, or None on failure."""

    def _call() -> str | None:
        payload = {"model": model, "messages": messages, "stream": False}
        if json_mode:
            payload["format"] = "json"
        req = urllib.request.Request(
            url.rstrip("/") + "/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return (data.get("message") or {}).get("content")

    try:
        return await asyncio.to_thread(_call)
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError) as e:
        logger.warning("Ollama call failed (%s); falling back", e)
        return None


async def ollama_available(url: str, timeout: float = 2.0) -> bool:
    def _ping() -> bool:
        with urllib.request.urlopen(url.rstrip("/") + "/api/tags", timeout=timeout) as resp:
            return resp.status == 200

    try:
        return await asyncio.to_thread(_ping)
    except Exception:
        return False
