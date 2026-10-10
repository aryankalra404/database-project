#!/usr/bin/env python3
import argparse
import asyncio
import json
import os
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.embeddings import HashingEmbedder, to_pgvector
from app.models import StrategyName
from app.planner import AdaptivePlanner, QueryFeatures, calculate_candidate_budget
from app.repository import ProductRepository
from scripts.benchmark import WORKLOAD, recall_at_k


@dataclass(frozen=True)
class AblationMeasurement:
    variant: str
    query_number: int
    selected_strategy: str
    latency_ms: float
    recall_at_k: float
    result_count: int
    fallback_used: bool


async def execute_variant(
    repository: ProductRepository,
    planner: AdaptivePlanner,
    observations,
    variant: str,
    query_text: str,
    filters,
    k: int,
    total_rows: int,
    truth_ids: list[int],
) -> tuple[StrategyName, float, list[dict], bool]:
    selectivity = await repository.estimate_selectivity(filters, total_rows)
    dynamic_budget = calculate_candidate_budget(k, selectivity, total_rows)
    real_features = QueryFeatures(
        selectivity, k, filters.predicate_count(), total_rows, dynamic_budget
    )

    planner_features = real_features
    execution_budget = dynamic_budget
    use_guard = True
    if variant == "no_feedback":
        decision = planner.cold_start(real_features)
    else:
        if variant == "no_selectivity":
            planner_features = QueryFeatures(1.0, k, filters.predicate_count(), total_rows, k * 10)
        elif variant == "fixed_candidate_budget":
            planner_features = QueryFeatures(
                selectivity, k, filters.predicate_count(), total_rows, k * 10
            )
            execution_budget = k * 10
        elif variant == "no_recall_guard":
            use_guard = False
        decision = planner.choose(planner_features, observations)

    vector = to_pgvector(HashingEmbedder().encode(query_text))
    result = await repository.search(decision.strategy, filters, vector, k, execution_budget)
    rows = result.rows
    latency_ms = result.latency_ms
    fallback_used = False
    expected_results = min(k, len(truth_ids))
    if (
        use_guard
        and len(rows) < expected_results
        and decision.strategy != StrategyName.EXACT_PREFILTER
    ):
        fallback = await repository.search(
            StrategyName.EXACT_PREFILTER, filters, vector, k, execution_budget
        )
        rows = fallback.rows
        latency_ms += fallback.latency_ms
        fallback_used = True
    return decision.strategy, latency_ms, rows, fallback_used


async def run(args: argparse.Namespace) -> None:
    database_url = os.getenv("DATABASE_URL", "postgresql://sahvs:sahvs@localhost:5432/sahvs")
    repository = ProductRepository(database_url)
    planner = AdaptivePlanner(minimum_observations=args.minimum_observations, exploration_rate=0)
    embedder = HashingEmbedder()
    variants = [
        "full",
        "no_feedback",
        "no_selectivity",
        "fixed_candidate_budget",
        "no_recall_guard",
    ]
    measurements: list[AblationMeasurement] = []

    await repository.open()
    try:
        observations = await repository.load_observations()
        counts = {strategy: 0 for strategy in StrategyName}
        for observation in observations:
            counts[observation.strategy] += 1
        missing = [
            strategy.value
            for strategy, count in counts.items()
            if count < args.minimum_observations
        ]
        if missing:
            raise RuntimeError(
                "Run scripts/benchmark.py first; insufficient observations for "
                + ", ".join(missing)
            )

        total_rows = max(await repository.total_rows(), 1)
        for query_number, (query_text, filters) in enumerate(WORKLOAD, start=1):
            selectivity = await repository.estimate_selectivity(filters, total_rows)
            budget = calculate_candidate_budget(args.k, selectivity, total_rows)
            vector = to_pgvector(embedder.encode(query_text))
            truth = await repository.search(
                StrategyName.EXACT_PREFILTER, filters, vector, args.k, budget
            )
            truth_ids = [row["id"] for row in truth.rows]

            for variant in variants:
                for _ in range(args.repetitions):
                    strategy, latency, rows, fallback_used = await execute_variant(
                        repository,
                        planner,
                        observations,
                        variant,
                        query_text,
                        filters,
                        args.k,
                        total_rows,
                        truth_ids,
                    )
                    ids = [row["id"] for row in rows]
                    measurements.append(
                        AblationMeasurement(
                            variant,
                            query_number,
                            strategy.value,
                            latency,
                            recall_at_k(ids, truth_ids),
                            len(rows),
                            fallback_used,
                        )
                    )
            print(f"Completed query {query_number}/{len(WORKLOAD)}", flush=True)
    finally:
        await repository.close()

    summary = {}
    for variant in variants:
        rows = [item for item in measurements if item.variant == variant]
        summary[variant] = {
            "mean_latency_ms": statistics.fmean(item.latency_ms for item in rows),
            "mean_recall_at_k": statistics.fmean(item.recall_at_k for item in rows),
            "full_result_rate": statistics.fmean(item.result_count >= args.k for item in rows),
            "fallback_rate": statistics.fmean(item.fallback_used for item in rows),
        }

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"ablation-{timestamp}.json"
    output_path.write_text(
        json.dumps(
            {
                "configuration": vars(args),
                "summary": summary,
                "measurements": [asdict(item) for item in measurements],
            },
            indent=2,
        )
    )
    print(json.dumps(summary, indent=2))
    print(f"Wrote {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SAHVS component ablation study")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--minimum-observations", type=int, default=8)
    parser.add_argument("--output", default="results")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
