"""Atomic replacement for fixed artifacts on the same filesystem."""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.core.errors import AppError


def atomic_write(path: Path, data: bytes, error_code: str) -> Path:
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
        os.replace(temporary, path)
    except OSError:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise AppError(503, error_code) from None
    return path
