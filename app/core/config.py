import logging
from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

INSECURE_DEFAULT_JWT_SECRET = "dev-only-insecure-secret-do-not-use-in-production"


class Settings(BaseSettings):
    jwt_secret: str = INSECURE_DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    app_name: str = "Business Location Intelligence API"
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/bizintel"
    redis_url: str = "redis://localhost:6379/0"
    allowed_origins: str = "http://localhost:3000"
    model_artifact_dir: str = "model_artifacts"
    gemini_api_key: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("database_url")
    @classmethod
    def _force_psycopg3_driver(cls, value: str) -> str:
        # Managed Postgres providers (Render among them) hand back a plain
        # postgres:// or postgresql:// URL. SQLAlchemy maps that bare scheme
        # to the legacy psycopg2 driver regardless of what's installed, and
        # this project only ships psycopg (v3), so left alone it fails with
        # "No module named 'psycopg2'" at connection time, not at import
        # time, which is why it only shows up once something tries to
        # actually connect. Force the +psycopg dialect explicitly.
        if value.startswith("postgres://"):
            value = "postgresql://" + value[len("postgres://"):]
        if value.startswith("postgresql://"):
            value = "postgresql+psycopg://" + value[len("postgresql://"):]
        return value

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.jwt_secret == INSECURE_DEFAULT_JWT_SECRET:
        if settings.app_env != "development":
            raise RuntimeError(
                "JWT_SECRET must be set to a real secret when APP_ENV is not 'development'."
            )
        logger.warning("Using the insecure default JWT_SECRET - fine for local development only.")
    return settings
