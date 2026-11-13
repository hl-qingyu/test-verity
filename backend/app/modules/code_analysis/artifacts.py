"""Private local storage for raw responses returned by code-analysis AI calls."""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.core.config import Settings
from app.core.errors import AppError


def result_directory() -> Path:
    return Settings().code_analysis_result_path.resolve()


def candidate_path(task_id: int) -> Path:
    return result_directory() / f"code-analysis-{task_id}-ai-candidate.txt"


def save_candidate(task_id: int, content: str) -> Path:
    directory = result_directory()
    target = directory / f"code-analysis-{task_id}-ai-candidate.txt"
    temporary = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=directory, prefix=f".{target.name}.", delete=False) as output:
            temporary = Path(output.name)
            output.write(content.encode("utf-8"))
        os.replace(temporary, target)
        return target
    except OSError:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise AppError(503, "code_candidate_storage_unavailable") from None
