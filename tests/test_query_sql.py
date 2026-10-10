from app.models import ProductFilters, StrategyName
from app.query_sql import build_count_plan_query, build_search_query, build_where


def test_filters_use_parameters_instead_of_string_values() -> None:
    hostile_value = "Laptops' OR TRUE --"
    where, parameters = build_where(ProductFilters(category=hostile_value))

    assert hostile_value not in where
    assert parameters["category"] == hostile_value
    assert "%(category)s" in where


def test_empty_filter_builds_true_predicate() -> None:
    where, parameters = build_where(ProductFilters())
    assert where == "TRUE"
    assert parameters == {}


def test_count_query_uses_explain_json() -> None:
    query = build_count_plan_query(ProductFilters(brand="Aster"))
    assert query.statement.startswith("EXPLAIN (FORMAT JSON)")
    assert query.parameters == {"brand": "Aster"}


def test_each_strategy_builds_a_distinct_query() -> None:
    filters = ProductFilters(category="Laptops")
    queries = {
        strategy: build_search_query(strategy, filters, "[0,1]", 10, 100).statement
        for strategy in StrategyName
    }

    assert "WITH candidates AS MATERIALIZED" in queries[StrategyName.ANN_POSTFILTER]
    assert "WHERE p.category" in queries[StrategyName.EXACT_PREFILTER]
    assert "WHERE p.category" in queries[StrategyName.ANN_ITERATIVE]
    assert len(set(queries.values())) == 2  # execution settings distinguish exact and iterative
