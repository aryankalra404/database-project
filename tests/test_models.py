import pytest
from pydantic import ValidationError

from app.models import ProductFilters, SearchRequest


def test_price_range_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        ProductFilters(min_price=100, max_price=50)


def test_predicate_count_ignores_empty_filters() -> None:
    filters = ProductFilters(category="Laptops", min_rating=4.0)
    assert filters.predicate_count() == 2


def test_search_k_is_bounded() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="laptop", k=51)
