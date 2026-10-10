CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS products (
    id BIGSERIAL PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    brand TEXT NOT NULL,
    price NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
    rating REAL NOT NULL CHECK (rating BETWEEN 0 AND 5),
    in_stock BOOLEAN NOT NULL DEFAULT TRUE,
    embedding VECTOR(384) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS products_category_idx ON products (category);
CREATE INDEX IF NOT EXISTS products_brand_idx ON products (brand);
CREATE INDEX IF NOT EXISTS products_price_idx ON products (price);
CREATE INDEX IF NOT EXISTS products_rating_idx ON products (rating);
CREATE INDEX IF NOT EXISTS products_stock_idx ON products (in_stock);
CREATE INDEX IF NOT EXISTS products_embedding_hnsw_idx
    ON products USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE TABLE IF NOT EXISTS query_observations (
    id BIGSERIAL PRIMARY KEY,
    query_fingerprint TEXT NOT NULL,
    strategy TEXT NOT NULL CHECK (
        strategy IN ('exact_prefilter', 'ann_postfilter', 'ann_iterative')
    ),
    estimated_selectivity DOUBLE PRECISION NOT NULL,
    requested_k INTEGER NOT NULL,
    predicate_count INTEGER NOT NULL,
    candidate_budget INTEGER NOT NULL,
    latency_ms DOUBLE PRECISION NOT NULL,
    result_count INTEGER NOT NULL,
    recall_at_k DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS query_observations_strategy_idx
    ON query_observations (strategy, created_at DESC);

CREATE TABLE IF NOT EXISTS experiment_runs (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    dataset_size INTEGER NOT NULL,
    query_count INTEGER NOT NULL,
    configuration JSONB NOT NULL,
    summary JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ANALYZE products;

