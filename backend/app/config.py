"""Local-only configuration; secrets are never required for the default workflow."""

import os
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "backend"


@dataclass(frozen=True)
class Settings:
    database: Path = Path(os.environ.get("FINSIGHT_DB", str(REPO / ".local/finsight.sqlite3")))
    model_cache: Path = REPO / ".local/models"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    ollama_url: str = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
    allow_ollama: bool = os.environ.get("FINSIGHT_ALLOW_OLLAMA", "false").lower() == "true"
    download_models: bool = os.environ.get("FINSIGHT_DOWNLOAD_MODELS", "false").lower() == "true"


settings = Settings()
