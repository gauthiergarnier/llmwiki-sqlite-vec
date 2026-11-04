"""Fixed-capacity admission control for extraction jobs."""

import contextlib
import logging
from collections.abc import Iterator

from fastapi import HTTPException

logger = logging.getLogger(__name__)


class ExtractionSlots:
    """Each job can spawn LibreOffice + a JVM, so unbounded concurrency OOMs the container."""

    def __init__(self, max_concurrent: int) -> None:
        self.max_concurrent = max_concurrent
        self.active = 0

    @contextlib.contextmanager
    def acquire(self) -> Iterator[None]:
        if self.active >= self.max_concurrent:
            logger.warning("extract rejected: at capacity (%d concurrent)", self.active)
            raise HTTPException(
                503,
                "Converter at capacity, retry shortly",
                headers={"Retry-After": "1"},
            )
        self.active += 1
        try:
            yield
        finally:
            self.active -= 1
