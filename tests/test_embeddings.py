import math

from app.embeddings import HashingEmbedder, to_pgvector


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def test_hash_embeddings_are_normalized_and_repeatable() -> None:
    embedder = HashingEmbedder(384)
    first = embedder.encode("sleek lightweight laptop")
    second = embedder.encode("sleek lightweight laptop")

    assert first == second
    assert len(first) == 384
    assert math.isclose(cosine(first, first), 1.0, rel_tol=1e-6)


def test_demo_synonyms_share_features() -> None:
    embedder = HashingEmbedder(384)
    sleek = embedder.encode("sleek laptop")
    modern = embedder.encode("modern laptop")

    assert cosine(sleek, modern) > 0.99


def test_pgvector_serialization() -> None:
    assert to_pgvector([0.25, -0.5]) == "[0.25000000,-0.50000000]"
