from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql://sahvs:sahvs@localhost:5432/sahvs"
    embedding_provider: str = "hash"
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimensions: int = 384
    planner_exploration_rate: float = 0.10
    planner_min_observations: int = 8
    postfilter_multiplier: int = 10

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
