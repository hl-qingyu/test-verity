from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

COOKIE_NAME = "verity_session"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env", extra="ignore"
    )

    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://verity:CHANGE_ME@127.0.0.1:5432/verity"
    )
    auth_allowed_origins: list[str] = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]
    auth_cookie_secure: bool = False
    document_storage_path: Path = Path(__file__).resolve().parents[2] / "storage" / "documents"
    code_analysis_result_path: Path = (
        Path(__file__).resolve().parents[2] / "storage" / "code-analysis-results"
    )
    change_analysis_result_path: Path = (
        Path(__file__).resolve().parents[2] / "storage" / "change-analysis-results"
    )
    case_generation_result_path: Path = (
        Path(__file__).resolve().parents[2] / "storage" / "case-generation-results"
    )
    requirement_analysis_result_path: Path = (
        Path(__file__).resolve().parents[2] / "storage" / "requirement-analysis-results"
    )
    ai_response_error_path: Path = (
        Path(__file__).resolve().parents[2] / "storage" / "ai-response-errors"
    )
    ai_encryption_key: SecretStr = SecretStr("")
    ai_max_concurrent: int = Field(default=2, ge=1, le=64)
    ai_max_per_user: int = Field(default=1, ge=1, le=64)
    ai_max_per_credential: int = Field(default=1, ge=1, le=64)
    ai_cli_executable: Path | None = None
    ai_cli_work_path: Path = Path(__file__).resolve().parents[2] / "storage" / "codex-exec"
    ai_allowed_base_urls: list[str] = [
        "https://api.openai.com/v1",
        "https://sub2api.geekuat.com",
        "https://sub2api.geekuat.com/v1",
    ]
