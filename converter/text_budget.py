"""Bounds the total text pulled out of one untrusted element tree."""

from typing import Any

from converter.bounds import bounded_utf8_size


class TextBudget:
    def __init__(self, max_bytes: int) -> None:
        self._remaining = max_bytes

    def take(self, value: Any, label: str, overhead: int = 0) -> str:
        size = bounded_utf8_size(value, self._remaining - overhead, label)
        self._remaining -= size + overhead
        return value
