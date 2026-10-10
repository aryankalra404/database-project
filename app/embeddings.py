import hashlib
import math
import re
from collections.abc import Iterable
from typing import Protocol

import numpy as np

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

# The zero-download provider maps a few product-search synonyms together. It is
# intended for the demo and test suite; experiments should use MiniLM.
SYNONYMS = {
    "sleek": "modern",
    "minimal": "modern",
    "minimalist": "modern",
    "stylish": "modern",
    "notebook": "laptop",
    "ultrabook": "laptop",
    "earbuds": "headphones",
    "earphones": "headphones",
    "cellphone": "phone",
    "smartphone": "phone",
    "cheap": "budget",
    "affordable": "budget",
    "portable": "lightweight",
}


class Embedder(Protocol):
    dimensions: int

    def encode(self, text: str) -> list[float]: ...


def _features(text: str) -> Iterable[str]:
    tokens = [SYNONYMS.get(token, token) for token in TOKEN_PATTERN.findall(text.lower())]
    yield from tokens
    for left, right in zip(tokens, tokens[1:], strict=False):
        yield f"{left}_{right}"


class HashingEmbedder:
    """Deterministic feature-hashing embedder with no model download."""

    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions

    def encode(self, text: str) -> list[float]:
        vector = np.zeros(self.dimensions, dtype=np.float32)
        for feature in _features(text):
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            value = int.from_bytes(digest, "little")
            index = value % self.dimensions
            sign = 1.0 if value & 1 else -1.0
            vector[index] += sign

        norm = float(np.linalg.norm(vector))
        if math.isclose(norm, 0.0):
            return vector.tolist()
        return (vector / norm).tolist()


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, dimensions: int = 384):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("Install the ML dependencies with `pip install -e '.[ml]'`") from exc
        self.model = SentenceTransformer(model_name)
        self.dimensions = dimensions

    def encode(self, text: str) -> list[float]:
        vector = self.model.encode(text, normalize_embeddings=True)
        if len(vector) != self.dimensions:
            raise ValueError(f"Model returned {len(vector)} dimensions; expected {self.dimensions}")
        return vector.astype(np.float32).tolist()


def create_embedder(provider: str, model_name: str, dimensions: int) -> Embedder:
    if provider == "hash":
        return HashingEmbedder(dimensions)
    if provider == "sentence-transformers":
        return SentenceTransformerEmbedder(model_name, dimensions)
    raise ValueError(f"Unknown embedding provider: {provider}")


def to_pgvector(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"
