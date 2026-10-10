#!/usr/bin/env python3
import argparse
import asyncio
import csv
import json
import os
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.embeddings import HashingEmbedder, to_pgvector
from app.models import ProductFilters, StrategyName
from app.planner import QueryFeatures, calculate_candidate_budget
from app.repository import ProductRepository

WORKLOAD = [
    ("lightweight modern laptop", ProductFilters(category="Laptops", max_price=70000)),
    ("budget phone with long battery", ProductFilters(category="Phones", max_price=25000)),
    ("noise cancelling headphones", ProductFilters(category="Audio", min_rating=4.0)),
    ("premium fitness watch", ProductFilters(category="Wearables", min_price=15000)),
    ("quiet smart appliance", ProductFilters(category="Home", in_stock=True)),
    ("portable wireless audio", ProductFilters(in_stock=True, max_price=10000)),
    ("professional computer", ProductFilters(brand="Aster", min_rating=4.2)),
    ("minimalist everyday device", ProductFilters(max_price=50000)),
    ("modern technology", ProductFilters(in_stock=True)),
    ("reliable product", ProductFilters()),
]


@dataclass(frozen=True)
class Measurement:
    query_number: int
    strategy: str
    selectivity: float
    matching_rows: int
    candidate_budget: int
    repetition: int
    latency_ms: float
    result_count: int
    recall_at_k: float


def recall_at_k(result_ids: list[int], truth_ids: list[int]) -> float:
    if not truth_ids:
        return 1.0
    return len(set(result_ids) & set(truth_ids)) / len(truth_ids)


async def run(args: argparse.Namespace) -> None:
    database_url = os.getenv("DATABASE_URL", "postgresql://sahvs:sahvs@localhost:5432/sahvs")
    repository = ProductRepository(database_url)
    embedder = HashingEmbedder()
    measurements: list[Measurement] = []
    await repository.open()
    try:
        total_rows = max(await repository.total_rows(), 1)
        for query_number, (query_text, filters) in enumerate(WORKLOAD, start=1):
            selectivity = await repository.estimate_selectivity(filters, total_rows)
            budget = calculate_candidate_budget(args.k, selectivity, total_rows)
            features = QueryFeatures(
                selectivity,
                args.k,
                filters.predicate_count(),
                total_rows,
                budget,
            )
            vector = to_pgvector(embedder.encode(query_text))
            truth = await repository.search(
                StrategyName.EXACT_PREFILTER, filters, vector, args.k, budget
            )
            truth_ids = [row["id"] for row in truth.rows]

            for strategy in StrategyName:
                for repetition in range(1, args.repetitions + 1):
                    result = await repository.search(strategy, filters, vector, args.k, budget)
                    result_ids = [row["id"] for row in result.rows]
                    recall = recall_at_k(result_ids, truth_ids)
                    measurement = Measurement(
                        query_number=query_number,
                        strategy=strategy.value,
                        selectivity=selectivity,
                        matching_rows=features.estimated_matching_rows,
                        candidate_budget=budget,
                        repetition=repetition,
                        latency_ms=result.latency_ms,
                        result_count=len(result.rows),
                        recall_at_k=recall,
                    )
                    measurements.append(measurement)
                    await repository.record_observation(
                        f"benchmark-{query_number}",
                        strategy,
                        features,
                        result.latency_ms,
                        len(result.rows),
                        recall,
                    )
            print(f"Completed query {query_number}/{len(WORKLOAD)}", flush=True)
    finally:
        await repository.close()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    csv_path = output_dir / f"benchmark-{timestamp}.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(measurements[0])))
        writer.writeheader()
        writer.writerows(asdict(item) for item in measurements)

    summary = {}
    for strategy in StrategyName:
        rows = [item for item in measurements if item.strategy == strategy.value]
        latencies = [item.latency_ms for item in rows]
        summary[strategy.value] = {
            "mean_latency_ms": statistics.fmean(latencies),
            "median_latency_ms": statistics.median(latencies),
            "p95_latency_ms": sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)],
            "mean_recall_at_k": statistics.fmean(item.recall_at_k for item in rows),
            "full_result_rate": statistics.fmean(item.result_count >= args.k for item in rows),
        }
    json_path = output_dir / f"benchmark-{timestamp}.json"
    json_path.write_text(json.dumps({"configuration": vars(args), "summary": summary}, indent=2))
    print(f"Wrote {csv_path}")
    print(f"Wrote {json_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark SAHVS query strategies")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--output", default="results")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
