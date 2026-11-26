"""Private local storage for raw responses returned by code-analysis AI calls."""

from pathlib import Path

from app.core.config import Settings
from app.core.files import atomic_write


def result_directory() -> Path:
    return Settings().code_analysis_result_path.resolve()


def candidate_path(task_id: int) -> Path:
    return result_directory() / f"code-analysis-{task_id}-ai-candidate.txt"


def save_candidate(task_id: int, content: str) -> Path:
    return atomic_write(
        candidate_path(task_id), content.encode("utf-8"), "code_candidate_storage_unavailable"
    )
