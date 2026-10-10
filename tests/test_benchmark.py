from scripts.benchmark import recall_at_k


def rows(*distances: float) -> list[dict]:
    return [{"distance": distance} for distance in distances]


def test_recall_accepts_different_results_at_the_kth_distance() -> None:
    truth = rows(0.1, 0.2, 0.3)
    result = rows(0.1, 0.3, 0.3)

    assert recall_at_k(result, truth) == 1.0


def test_recall_penalizes_missing_and_worse_results() -> None:
    truth = rows(0.1, 0.2, 0.3)

    assert recall_at_k(rows(0.1, 0.2), truth) == 2 / 3
    assert recall_at_k(rows(0.1, 0.2, 0.4), truth) == 2 / 3


def test_empty_ground_truth_has_perfect_recall() -> None:
    assert recall_at_k([], []) == 1.0
