import re
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import COOKIE_NAME, Settings
from app.core.errors import AppError
from app.db.models import UserAccount
from app.db.session import get_db
from app.modules.auth import service as auth_service
from app.security.rate_limit import limit_requests

DB = Annotated[Session, Depends(get_db)]


def check_origin(request: Request) -> None:
    if request.headers.get("origin") not in Settings().auth_allowed_origins:
        raise AppError(403, "origin_not_allowed")


def limit_login(request: Request, bucket: str = "login") -> None:
    limit_requests(request.client.host if request.client else "unknown", bucket)


def read_cookie(request: Request) -> str | None:
    value = request.cookies.get(COOKIE_NAME, "")
    return value if re.fullmatch(r"[A-Za-z0-9_-]{43}", value) else None


def require_user(request: Request, db: DB) -> UserAccount:
    return auth_service.authenticate(read_cookie(request), db)


Actor = Annotated[UserAccount, Depends(require_user)]


def require_admin(user: Actor) -> UserAccount:
    if user.platform_role != "ADMIN":
        raise AppError(403, "admin_required")
    return user


Admin = Annotated[UserAccount, Depends(require_admin)]
