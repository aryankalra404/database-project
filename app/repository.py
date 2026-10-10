import time
from dataclasses import dataclass
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.models import ProductFilters, StrategyName
from app.planner import PlannerObservation, QueryFeatures
from app.query_sql import build_count_plan_query, build_search_query


@dataclass(frozen=True)
class QueryResult:
    rows: list[dict[str, Any]]
    latency_ms: float


class ProductRepository:
    def __init__(self, database_url: str):
        self.pool = AsyncConnectionPool(
            database_url,
            min_size=1,
            max_size=8,
            open=False,
            kwargs={"row_factory": dict_row},
        )

    async def open(self) -> None:
        await self.pool.open(wait=True, timeout=20)

    async def close(self) -> None:
        await self.pool.close()

    async def health(self) -> tuple[bool, int]:
        async with self.pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT count(*) AS count FROM products")
                row = await cursor.fetchone()
        return True, int(row["count"])

    async def total_rows(self) -> int:
        async with self.pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT greatest(reltuples::bigint, 0) AS rows "
                    "FROM pg_class WHERE oid = 'products'::regclass"
                )
                row = await cursor.fetchone()
        return int(row["rows"])

    async def estimate_selectivity(self, filters: ProductFilters, total_rows: int) -> float:
        if filters.predicate_count() == 0:
            return 1.0
        query = build_count_plan_query(filters)
        async with self.pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(query.statement, query.parameters)
                row = await cursor.fetchone()
        plan_document = row["QUERY PLAN"]
        if isinstance(plan_document, str):
            import json

            plan_document = json.loads(plan_document)
        estimated_rows = int(plan_document[0]["Plan"].get("Plan Rows", 0))
        return min(1.0, max(1.0 / max(total_rows, 1), estimated_rows / max(total_rows, 1)))

    async def search(
        self,
        strategy: StrategyName,
        filters: ProductFilters,
        vector: str,
        k: int,
        candidate_budget: int,
    ) -> QueryResult:
        query = build_search_query(strategy, filters, vector, k, candidate_budget)
        started = time.perf_counter()
        async with self.pool.connection() as connection:
            async with connection.transaction():
                async with connection.cursor() as cursor:
                    if strategy == StrategyName.EXACT_PREFILTER:
                        await cursor.execute("SET LOCAL enable_indexscan = off")
                        await cursor.execute("SET LOCAL enable_bitmapscan = off")
                    elif strategy == StrategyName.ANN_ITERATIVE:
                        await cursor.execute(
                            "SELECT set_config('hnsw.iterative_scan', 'strict_order', true)"
                        )
                        ef_search = min(1_000, max(40, candidate_budget))
                        await cursor.execute(
                            "SELECT set_config('hnsw.ef_search', %s, true)", (str(ef_search),)
                        )
                    await cursor.execute(query.statement, query.parameters)
                    rows = await cursor.fetchall()
        latency_ms = (time.perf_counter() - started) * 1_000
        return QueryResult(rows, latency_ms)

    async def load_observations(self, limit: int = 1_000) -> list[PlannerObservation]:
        statement = """
            SELECT strategy, estimated_selectivity, requested_k, predicate_count,
                   candidate_budget, latency_ms, result_count,
                   (SELECT greatest(reltuples::bigint, 0)
                    FROM pg_class WHERE oid = 'products'::regclass) AS total_rows
            FROM query_observations
            ORDER BY created_at DESC
            LIMIT %s
        """
        async with self.pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(statement, (limit,))
                rows = await cursor.fetchall()
        return [
            PlannerObservation(
                strategy=StrategyName(row["strategy"]),
                features=QueryFeatures(
                    selectivity=float(row["estimated_selectivity"]),
                    requested_k=int(row["requested_k"]),
                    predicate_count=int(row["predicate_count"]),
                    total_rows=int(row["total_rows"]),
                    candidate_budget=int(row["candidate_budget"]),
                ),
                latency_ms=float(row["latency_ms"]),
                result_count=int(row["result_count"]),
            )
            for row in rows
        ]

    async def record_observation(
        self,
        fingerprint: str,
        strategy: StrategyName,
        features: QueryFeatures,
        latency_ms: float,
        result_count: int,
        recall_at_k: float | None = None,
    ) -> None:
        statement = """
            INSERT INTO query_observations (
                query_fingerprint, strategy, estimated_selectivity, requested_k,
                predicate_count, candidate_budget, latency_ms, result_count, recall_at_k
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        values = (
            fingerprint,
            strategy.value,
            features.selectivity,
            features.requested_k,
            features.predicate_count,
            features.candidate_budget,
            latency_ms,
            result_count,
            recall_at_k,
        )
        async with self.pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(statement, values)
            await connection.commit()

    async def planner_summary(self) -> list[dict[str, Any]]:
        statement = """
            SELECT strategy, count(*) AS executions,
                   round(avg(latency_ms)::numeric, 2) AS mean_latency_ms,
                   round(avg(result_count)::numeric, 2) AS mean_results,
                   round(avg(recall_at_k)::numeric, 4) AS mean_recall
            FROM query_observations
            GROUP BY strategy
            ORDER BY strategy
        """
        async with self.pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(statement)
                return await cursor.fetchall()
