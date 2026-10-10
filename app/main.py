import hashlib
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.embeddings import create_embedder, to_pgvector
from app.models import HealthResponse, ProductResult, SearchRequest, SearchResponse, StrategyName
from app.planner import AdaptivePlanner, QueryFeatures, calculate_candidate_budget
from app.repository import ProductRepository

settings = get_settings()
repository = ProductRepository(settings.database_url)
embedder = create_embedder(
    settings.embedding_provider, settings.model_name, settings.embedding_dimensions
)
planner = AdaptivePlanner(
    minimum_observations=settings.planner_min_observations,
    exploration_rate=settings.planner_exploration_rate,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(runtime_app: FastAPI):
    runtime_app.state.database_ready = False
    try:
        await repository.open()
        runtime_app.state.database_ready = True
    except Exception:
        # Keep the interface available when a deployment has not been connected
        # to PostgreSQL yet. Database-backed endpoints return an actionable 503.
        logger.exception("PostgreSQL connection failed during application startup")

    yield

    if runtime_app.state.database_ready:
        await repository.close()


app = FastAPI(
    title="SAHVS",
    description="Adaptive query planning for hybrid vector and metadata search",
    version="0.1.0",
    lifespan=lifespan,
)

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


def require_database() -> None:
    if not getattr(app.state, "database_ready", False):
        raise HTTPException(
            status_code=503,
            detail=(
                "Database is not configured. Set DATABASE_URL to a hosted PostgreSQL "
                "database with pgvector, then redeploy."
            ),
        )


@app.get("/", include_in_schema=False)
async def home() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    require_database()
    try:
        _, count = await repository.health()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database is unavailable") from exc
    return HealthResponse(status="ok", database="connected", product_count=count)


@app.post("/api/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    require_database()
    total_rows = max(await repository.total_rows(), 1)
    selectivity = await repository.estimate_selectivity(request.filters, total_rows)
    candidate_budget = calculate_candidate_budget(
        request.k, selectivity, total_rows, settings.postfilter_multiplier
    )
    features = QueryFeatures(
        selectivity=selectivity,
        requested_k=request.k,
        predicate_count=request.filters.predicate_count(),
        total_rows=total_rows,
        candidate_budget=candidate_budget,
    )

    if request.strategy is None:
        observations = await repository.load_observations()
        decision = planner.choose(features, observations)
    else:
        from app.planner import PlanDecision

        decision = PlanDecision(request.strategy, "The request forced this strategy")

    vector = to_pgvector(embedder.encode(request.query))
    result = await repository.search(
        decision.strategy, request.filters, vector, request.k, candidate_budget
    )
    selected_strategy = decision.strategy
    fallback_used = False
    expected_results = min(request.k, features.estimated_matching_rows)

    if len(result.rows) < expected_results and decision.strategy != StrategyName.EXACT_PREFILTER:
        fallback = await repository.search(
            StrategyName.EXACT_PREFILTER,
            request.filters,
            vector,
            request.k,
            candidate_budget,
        )
        result = type(result)(fallback.rows, result.latency_ms + fallback.latency_ms)
        fallback_used = True

    fingerprint_payload = {
        "query": request.query.lower().strip(),
        "filters": request.filters.model_dump(),
        "k": request.k,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True).encode()
    ).hexdigest()[:20]
    if request.learn:
        await repository.record_observation(
            fingerprint,
            selected_strategy,
            features,
            result.latency_ms,
            len(result.rows),
        )

    return SearchResponse(
        results=[ProductResult(**row) for row in result.rows],
        selected_strategy=selected_strategy,
        selection_reason=decision.reason,
        estimated_selectivity=selectivity,
        estimated_matching_rows=features.estimated_matching_rows,
        candidate_budget=candidate_budget,
        query_latency_ms=result.latency_ms,
        fallback_used=fallback_used,
    )


@app.get("/api/planner/summary")
async def planner_summary() -> list[dict[str, object]]:
    require_database()
    return await repository.planner_summary()
