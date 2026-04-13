from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = ""

    # LLM provider config (OpenAI-compatible endpoint)
    llm_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "deepseek/deepseek-chat-v3-0324"

    # SEC EDGAR — required by SEC's fair-access policy. Format: "App Name email@domain.com"
    edgar_user_agent: str = ""

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
