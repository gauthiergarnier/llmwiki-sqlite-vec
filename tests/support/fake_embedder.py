"""Deterministic stand-in for shared/embedder.py (fork: hybrid search tests).

Maps words to a handful of "concept" dimensions so synonyms land close together
without loading sentence-transformers. Install with ``install(monkeypatch)``.
"""

import math
import os
import sys

_SHARED = os.path.join(os.path.dirname(__file__), "..", "..", "shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import embedder  # noqa: E402

CONCEPTS = [
    {"car", "cars", "automobile", "vehicle", "vehicles"},
    {"budget", "cost", "costs", "pricing", "price", "spend"},
    {"partner", "partners", "alliance", "alliances", "reseller"},
]


def fake_embed(text: str) -> list[float]:
    vec = [0.0] * embedder.EMBEDDING_DIM
    for word in text.lower().replace(".", " ").replace(",", " ").split():
        for i, concept in enumerate(CONCEPTS):
            if word in concept:
                vec[i] += 1.0
    vec[len(CONCEPTS)] += 0.05  # never all-zero
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec]


def install(monkeypatch) -> list[int]:
    """Patch the embedder; returns a list that records each embed_texts batch size."""
    calls: list[int] = []

    def embed_texts(texts):
        calls.append(len(texts))
        return [fake_embed(t) for t in texts]

    monkeypatch.setattr(embedder, "embed_texts", embed_texts)
    monkeypatch.setattr(embedder, "embed_query", lambda q: fake_embed(q))
    return calls
