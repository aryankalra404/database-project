#!/usr/bin/env python3
import argparse
import os
import random
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.embeddings import HashingEmbedder, SentenceTransformerEmbedder, to_pgvector


CATALOG = {
    "Laptops": {
        "brands": ["Aster", "Nova", "Orbit", "Vertex"],
        "nouns": ["laptop", "notebook", "ultrabook", "workstation"],
        "traits": ["lightweight", "gaming", "business", "modern", "student"],
        "prices": (28000, 165000),
    },
    "Phones": {
        "brands": ["Nova", "Pixelon", "Sora", "Vertex"],
        "nouns": ["smartphone", "phone", "mobile phone"],
        "traits": ["compact", "camera focused", "budget", "premium", "long battery"],
        "prices": (7000, 110000),
    },
    "Audio": {
        "brands": ["Echo", "Pulse", "Sonic", "Aster"],
        "nouns": ["headphones", "earbuds", "speaker", "soundbar"],
        "traits": ["wireless", "noise cancelling", "portable", "studio", "budget"],
        "prices": (800, 45000),
    },
    "Wearables": {
        "brands": ["Pulse", "Sora", "Orbit", "Echo"],
        "nouns": ["smartwatch", "fitness band", "sports watch"],
        "traits": ["fitness", "minimalist", "rugged", "lightweight", "premium"],
        "prices": (1200, 65000),
    },
    "Home": {
        "brands": ["Haven", "Aster", "Luma", "Nova"],
        "nouns": ["air purifier", "desk lamp", "robot vacuum", "coffee maker"],
        "traits": ["quiet", "energy efficient", "smart", "compact", "modern"],
        "prices": (1000, 80000),
    },
}

COLORS = ["black", "silver", "blue", "white", "graphite", "green"]
MATERIALS = ["aluminium", "recycled plastic", "steel", "soft-touch polymer"]


def make_product(index: int, rng: random.Random) -> tuple[str, ... | float | bool]:
    category = rng.choice(list(CATALOG))
    details = CATALOG[category]
    brand = rng.choice(details["brands"])
    noun = rng.choice(details["nouns"])
    trait = rng.choice(details["traits"])
    color = rng.choice(COLORS)
    material = rng.choice(MATERIALS)
    price_low, price_high = details["prices"]
    price = round(rng.uniform(price_low, price_high), 2)
    rating = round(min(5.0, max(1.0, rng.gauss(4.0, 0.55))), 1)
    in_stock = rng.random() > 0.13
    series = rng.randint(10, 999)
    title = f"{brand} {series} {trait.title()} {noun.title()}"
    description = (
        f"A {trait} {color} {noun} made with {material}. "
        f"Designed for reliable everyday use in the {category.lower()} category."
    )
    return (
        f"SAHVS-{index:07d}",
        title,
        description,
        category,
        brand,
        price,
        rating,
        in_stock,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a reproducible product-search dataset")
    parser.add_argument("--count", type=int, default=50_000)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    database_url = os.getenv(
        "DATABASE_URL", "postgresql://sahvs:sahvs@localhost:5432/sahvs"
    )
    provider = os.getenv("EMBEDDING_PROVIDER", "hash")
    if provider == "sentence-transformers":
        embedder = SentenceTransformerEmbedder(
            os.getenv("MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")
        )
    else:
        embedder = HashingEmbedder()

    rng = random.Random(args.seed)
    insert = """
        INSERT INTO products (
            sku, title, description, category, brand, price, rating, in_stock, embedding
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
        ON CONFLICT (sku) DO UPDATE SET
            title = excluded.title,
            description = excluded.description,
            category = excluded.category,
            brand = excluded.brand,
            price = excluded.price,
            rating = excluded.rating,
            in_stock = excluded.in_stock,
            embedding = excluded.embedding
    """

    with psycopg.connect(database_url) as connection:
        if args.replace:
            connection.execute("TRUNCATE products RESTART IDENTITY")
        for start in range(0, args.count, args.batch_size):
            rows = []
            stop = min(start + args.batch_size, args.count)
            for index in range(start, stop):
                product = make_product(index, rng)
                text = f"{product[1]}. {product[2]}"
                rows.append((*product, to_pgvector(embedder.encode(text))))
            with connection.cursor() as cursor:
                cursor.executemany(insert, rows)
            connection.commit()
            print(f"Loaded {stop:,}/{args.count:,} products", flush=True)
        connection.execute("ANALYZE products")
        connection.commit()


if __name__ == "__main__":
    main()

