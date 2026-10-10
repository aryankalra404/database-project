from app.models import StrategyName
from app.planner import (
    AdaptivePlanner,
    PlannerObservation,
    QueryFeatures,
    calculate_candidate_budget,
)


def features(selectivity: float, total_rows: int = 100_000) -> QueryFeatures:
    return QueryFeatures(
        selectivity=selectivity,
        requested_k=10,
        predicate_count=2,
        total_rows=total_rows,
        candidate_budget=calculate_candidate_budget(10, selectivity, total_rows),
    )


def test_candidate_budget_compensates_for_selectivity() -> None:
    assert calculate_candidate_budget(10, 0.50, 100_000) == 100
    assert calculate_candidate_budget(10, 0.01, 100_000) == 1_250
    assert calculate_candidate_budget(10, 0.00001, 100_000) == 100_000


def test_cold_start_uses_exact_search_for_tiny_result_sets() -> None:
    decision = AdaptivePlanner.cold_start(features(0.001))
    assert decision.strategy == StrategyName.EXACT_PREFILTER


def test_cold_start_uses_postfilter_for_broad_filters() -> None:
    decision = AdaptivePlanner.cold_start(features(0.75))
    assert decision.strategy == StrategyName.ANN_POSTFILTER


def test_learned_model_selects_observed_fast_strategy() -> None:
    target = features(0.40)
    observations = []
    for strategy, latency in (
        (StrategyName.EXACT_PREFILTER, 80.0),
        (StrategyName.ANN_POSTFILTER, 8.0),
        (StrategyName.ANN_ITERATIVE, 25.0),
    ):
        for _ in range(4):
            observations.append(PlannerObservation(strategy, target, latency, 10))

    planner = AdaptivePlanner(minimum_observations=4, exploration_rate=0)
    assert planner.choose(target, observations).strategy == StrategyName.ANN_POSTFILTER


def test_incomplete_results_receive_a_training_penalty() -> None:
    target = features(0.10)
    complete = [PlannerObservation(StrategyName.ANN_ITERATIVE, target, 20.0, 10) for _ in range(4)]
    incomplete = [PlannerObservation(StrategyName.ANN_POSTFILTER, target, 1.0, 2) for _ in range(4)]
    exact = [PlannerObservation(StrategyName.EXACT_PREFILTER, target, 60.0, 10) for _ in range(4)]

    planner = AdaptivePlanner(minimum_observations=4, exploration_rate=0)
    decision = planner.choose(target, complete + incomplete + exact)
    assert decision.strategy == StrategyName.ANN_ITERATIVE


def test_low_recall_receives_a_training_penalty() -> None:
    target = features(0.10)
    low_recall = [
        PlannerObservation(StrategyName.ANN_POSTFILTER, target, 1.0, 10, 0.2) for _ in range(4)
    ]
    high_recall = [
        PlannerObservation(StrategyName.ANN_ITERATIVE, target, 8.0, 10, 1.0) for _ in range(4)
    ]
    exact = [
        PlannerObservation(StrategyName.EXACT_PREFILTER, target, 60.0, 10, 1.0) for _ in range(4)
    ]

    planner = AdaptivePlanner(minimum_observations=4, exploration_rate=0)
    decision = planner.choose(target, low_recall + high_recall + exact)
    assert decision.strategy == StrategyName.ANN_ITERATIVE
