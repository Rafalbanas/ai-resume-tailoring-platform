from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_username: str | None = None
    app_password: str | None = None
    csrf_secret: str = "change-this-csrf-secret"
    base_url: str = "http://localhost:8000"
    data_dir: Path = Path("data")
    n8n_webhook_url: str = ""
    n8n_webhook_secret: str = ""
    ai_provider: str = Field(default="mock", pattern="^(mock|n8n|ollama)$")
    request_timeout_seconds: float = 60.0
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:9b"
    ollama_timeout_seconds: float = 300.0
    reference_cv_max_bytes: int = 10_000_000
    max_job_description_chars: int = 30_000
    rate_limit_per_minute: int = 20
    job_fetch_timeout_seconds: float = 12.0
    job_fetch_max_bytes: int = 2_000_000
    job_fetch_max_redirects: int = 3
    job_fetch_playwright_enabled: bool = True

    @property
    def master_profile_path(self) -> Path:
        return self.data_dir / "master_profile.json"

    @property
    def auth_file_path(self) -> Path:
        return self.data_dir / "auth.json"

    @property
    def reference_cvs_path(self) -> Path:
        return self.data_dir / "reference_cvs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
