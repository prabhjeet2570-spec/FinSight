from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = ""
    gemini_api_key: str = ""

    # File upload limits
    max_file_size_mb: int = 10
    max_files: int = 4
    max_total_size_mb: int = 40

    # CORS — comma-separated origins for production
    frontend_url: str = "http://localhost:5173"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def cors_origins(self) -> list[str]:
        """Parse FRONTEND_URL into a list of origins (supports comma-separated)."""
        return [o.strip() for o in self.frontend_url.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
