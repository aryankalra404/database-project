from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class StrategyName(StrEnum):
    EXACT_PREFILTER = "exact_prefilter"
    ANN_POSTFILTER = "ann_postfilter"
    ANN_ITERATIVE = "ann_iterative"


class ProductFilters(BaseModel):
    category: str | None = None
    brand: str | None = None
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    min_rating: float | None = Field(default=None, ge=0, le=5)
    in_stock: bool | None = None

    @model_validator(mode="after")
    def validate_price_range(self) -> "ProductFilters":
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("min_price cannot exceed max_price")
        return self

    def predicate_count(self) -> int:
        return sum(value is not None for value in self.model_dump().values())


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    filters: ProductFilters = Field(default_factory=ProductFilters)
    k: int = Field(default=10, ge=1, le=50)
    strategy: StrategyName | None = None
    learn: bool = True


class ProductResult(BaseModel):
    id: int
    sku: str
    title: str
    description: str
    category: str
    brand: str
    price: float
    rating: float
    in_stock: bool
    distance: float


class SearchResponse(BaseModel):
    results: list[ProductResult]
    selected_strategy: StrategyName
    selection_reason: str
    estimated_selectivity: float
    estimated_matching_rows: int
    candidate_budget: int
    query_latency_ms: float
    fallback_used: bool


class HealthResponse(BaseModel):
    status: str
    database: str
    product_count: int

