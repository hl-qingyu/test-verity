"""Private raw AI candidates for requirement analysis; never served without project access."""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.core.config import Settings
from app.core.errors import AppError


def candidate_path(task_id: int) -> Path:
    return (
        Settings().requirement_analysis_result_path.resolve()
        / f"requirement-analysis-{task_id}-ai-candidate.txt"
    )


def save_candidate(task_id: int, content: str) -> None:
    target = candidate_path(task_id)
    temporary = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            dir=target.parent, prefix=f".{target.name}.", delete=False
        ) as output:
            temporary = Path(output.name)
            output.write(content.encode("utf-8"))
        os.replace(temporary, target)
    except OSError:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise AppError(503, "risk_candidate_storage_unavailable") from None
