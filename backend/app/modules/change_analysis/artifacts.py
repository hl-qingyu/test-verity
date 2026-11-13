"""Private atomic AI candidates and project-scoped, verified Git blob storage."""

import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations.github import blob_sha


def result_directory() -> Path:
    return Settings().change_analysis_result_path.resolve()


def candidate_path(task_id: int) -> Path:
    return result_directory() / f"change-analysis-{task_id}-ai-candidate.txt"


def _save(target: Path, content: bytes, error_code: str) -> Path:
    directory = target.parent
    temporary = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=directory, prefix=f".{target.name}.", delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
        os.replace(temporary, target)
        return target
    except OSError:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise AppError(503, error_code) from None


def save_candidate(task_id: int, content: str) -> Path:
    return _save(
        candidate_path(task_id), content.encode("utf-8"), "change_candidate_storage_unavailable"
    )


def batch_candidate_path(task_id: int, batch_id: int) -> Path:
    return (
        result_directory() / f"change-analysis-{int(task_id)}-batch-{int(batch_id)}-candidate.txt"
    )


def save_batch_candidate(task_id: int, batch_id: int, content: str) -> Path:
    return _save(
        batch_candidate_path(task_id, batch_id),
        content.encode("utf-8"),
        "change_candidate_storage_unavailable",
    )


def _blob_path(project_id: int, repository_id: int, sha: str) -> Path:
    if project_id <= 0 or repository_id <= 0 or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise AppError(422, "github_invalid_response")
    return result_directory() / "git-blobs" / str(project_id) / str(repository_id) / sha


def load_blob(project_id: int, repository_id: int, sha: str) -> bytes | None:
    try:
        with _blob_path(project_id, repository_id, sha).open("rb") as stream:
            content = stream.read()
    except FileNotFoundError:
        return None
    except OSError:
        raise AppError(503, "change_source_storage_unavailable") from None
    return content if blob_sha(content) == sha else None


def save_blob(project_id: int, repository_id: int, sha: str, content: bytes) -> None:
    if blob_sha(content) != sha:
        raise AppError(502, "github_invalid_response")
    _save(_blob_path(project_id, repository_id, sha), content, "change_source_storage_unavailable")
