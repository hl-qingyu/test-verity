"""Private raw AI candidates for requirement analysis; never served without project access."""

from pathlib import Path

from app.core.config import Settings
from app.core.files import atomic_write


def candidate_path(task_id: int) -> Path:
    return (
        Settings().requirement_analysis_result_path.resolve()
        / f"requirement-analysis-{task_id}-ai-candidate.txt"
    )


def save_candidate(task_id: int, content: str) -> None:
    atomic_write(
        candidate_path(task_id), content.encode("utf-8"), "risk_candidate_storage_unavailable"
    )
