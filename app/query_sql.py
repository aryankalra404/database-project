from dataclasses import dataclass

from app.models import ProductFilters, StrategyName


@dataclass(frozen=True)
class BuiltQuery:
    statement: str
    parameters: dict[str, object]


RESULT_COLUMNS = """p.id, p.sku, p.title, p.description, p.category, p.brand,
       p.price, p.rating, p.in_stock"""


def build_where(filters: ProductFilters, alias: str = "p") -> tuple[str, dict[str, object]]:
    clauses: list[str] = []
    parameters: dict[str, object] = {}

    fields = (
        ("category", "=", filters.category),
        ("brand", "=", filters.brand),
        ("price", ">=", filters.min_price),
        ("price", "<=", filters.max_price),
        ("rating", ">=", filters.min_rating),
        ("in_stock", "=", filters.in_stock),
    )
    names = ("category", "brand", "min_price", "max_price", "min_rating", "in_stock")
    for name, (column, operator, value) in zip(names, fields, strict=True):
        if value is not None:
            clauses.append(f"{alias}.{column} {operator} %({name})s")
            parameters[name] = value

    return (" AND ".join(clauses) if clauses else "TRUE"), parameters


def build_count_plan_query(filters: ProductFilters) -> BuiltQuery:
    where, parameters = build_where(filters)
    return BuiltQuery(f"EXPLAIN (FORMAT JSON) SELECT 1 FROM products p WHERE {where}", parameters)


def build_search_query(
    strategy: StrategyName,
    filters: ProductFilters,
    vector: str,
    k: int,
    candidate_budget: int,
) -> BuiltQuery:
    where, parameters = build_where(filters)
    parameters.update(vector=vector, k=k, candidate_budget=candidate_budget)

    if strategy == StrategyName.EXACT_PREFILTER:
        statement = f"""
            SELECT {RESULT_COLUMNS}, p.embedding <=> %(vector)s::vector AS distance
            FROM products p
            WHERE {where}
            ORDER BY distance
            LIMIT %(k)s
        """
    elif strategy == StrategyName.ANN_POSTFILTER:
        outer_where, outer_parameters = build_where(filters, alias="c")
        parameters.update(outer_parameters)
        statement = f"""
            WITH candidates AS MATERIALIZED (
                SELECT p.id, p.sku, p.title, p.description, p.category, p.brand,
                       p.price, p.rating, p.in_stock,
                       p.embedding <=> %(vector)s::vector AS distance
                FROM products p
                ORDER BY p.embedding <=> %(vector)s::vector
                LIMIT %(candidate_budget)s
            )
            SELECT c.id, c.sku, c.title, c.description, c.category, c.brand,
                   c.price, c.rating, c.in_stock, c.distance
            FROM candidates c
            WHERE {outer_where}
            ORDER BY c.distance
            LIMIT %(k)s
        """
    elif strategy == StrategyName.ANN_ITERATIVE:
        statement = f"""
            SELECT {RESULT_COLUMNS}, p.embedding <=> %(vector)s::vector AS distance
            FROM products p
            WHERE {where}
            ORDER BY distance
            LIMIT %(k)s
        """
    else:
        raise ValueError(f"Unsupported strategy: {strategy}")

    return BuiltQuery("\n".join(line.strip() for line in statement.splitlines()), parameters)
