import math
import random
from dataclasses import dataclass

import numpy as np

from app.models import StrategyName


@dataclass(frozen=True)
class QueryFeatures:
    selectivity: float
    requested_k: int
    predicate_count: int
    total_rows: int
    candidate_budget: int

    @property
    def estimated_matching_rows(self) -> int:
        return max(0, round(self.total_rows * self.selectivity))

    def as_vector(self) -> np.ndarray:
        return np.array(
            [
                1.0,
                math.log10(self.total_rows + 1) / 7.0,
                self.selectivity,
                math.sqrt(self.selectivity),
                self.requested_k / 50.0,
                self.predicate_count / 6.0,
                min(self.candidate_budget, 10_000) / 10_000.0,
            ],
            dtype=np.float64,
        )


@dataclass(frozen=True)
class PlannerObservation:
    strategy: StrategyName
    features: QueryFeatures
    latency_ms: float
    result_count: int


@dataclass(frozen=True)
class PlanDecision:
    strategy: StrategyName
    reason: str
    predicted_latency_ms: float | None = None


class AdaptivePlanner:
    """Per-strategy ridge models with a safe heuristic cold start."""

    def __init__(
        self,
        minimum_observations: int = 8,
        exploration_rate: float = 0.10,
        random_seed: int = 7,
    ):
        self.minimum_observations = minimum_observations
        self.exploration_rate = exploration_rate
        self.random = random.Random(random_seed)

    @staticmethod
    def cold_start(features: QueryFeatures) -> PlanDecision:
        if features.estimated_matching_rows <= max(200, features.requested_k * 8):
            return PlanDecision(
                StrategyName.EXACT_PREFILTER,
                "A selective filter makes an exact scan of the matching rows inexpensive",
            )
        if features.selectivity < 0.20:
            return PlanDecision(
                StrategyName.ANN_ITERATIVE,
                "The filter is selective enough to need filtered HNSW traversal",
            )
        return PlanDecision(
            StrategyName.ANN_POSTFILTER,
            "The broad filter can use a bounded HNSW candidate set",
        )

    def choose(
        self, features: QueryFeatures, observations: list[PlannerObservation]
    ) -> PlanDecision:
        grouped = {
            strategy: [item for item in observations if item.strategy == strategy]
            for strategy in StrategyName
        }
        if any(len(items) < self.minimum_observations for items in grouped.values()):
            return self.cold_start(features)

        if self.random.random() < self.exploration_rate:
            strategy = self.random.choice(list(StrategyName))
            return PlanDecision(strategy, "Exploration sample used to keep the cost model current")

        predictions = {
            strategy: self._predict(features, items) for strategy, items in grouped.items()
        }
        strategy = min(predictions, key=predictions.get)
        latency = predictions[strategy]
        return PlanDecision(
            strategy,
            f"The learned cost model predicted the lowest latency at {latency:.2f} ms",
            latency,
        )

    @staticmethod
    def _predict(features: QueryFeatures, observations: list[PlannerObservation]) -> float:
        x = np.vstack([item.features.as_vector() for item in observations])
        y = np.array(
            [
                item.latency_ms
                + (1_000.0 if item.result_count < item.features.requested_k else 0.0)
                for item in observations
            ]
        )
        regularization = np.eye(x.shape[1]) * 0.1
        regularization[0, 0] = 0.0
        weights = np.linalg.solve(x.T @ x + regularization, x.T @ y)
        return max(0.0, float(features.as_vector() @ weights))


def calculate_candidate_budget(
    k: int, selectivity: float, total_rows: int, multiplier: int = 10
) -> int:
    selectivity = max(selectivity, 1.0 / max(total_rows, 1))
    expected = math.ceil((k / selectivity) * 1.25)
    return min(total_rows, max(k * multiplier, expected))

