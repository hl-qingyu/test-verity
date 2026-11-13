from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.api.dependencies import DB, check_origin, limit_login, read_cookie, require_user
from app.api.encryption import ChallengeInput, EncryptedRequest, decrypt_payload, issue_challenge
from app.core.config import COOKIE_NAME, Settings
from app.db.models import UserAccount
from app.modules.auth import service
from app.modules.auth.schemas import LoginInput, UserView

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/password-challenge", dependencies=[Depends(check_origin)])
def password_challenge(payload: ChallengeInput, request: Request) -> dict[str, str | int]:
    limit_login(request, "password_challenge")
    return issue_challenge(payload.path, request)


@router.post("/login", response_model=UserView, dependencies=[Depends(check_origin)])
def login(envelope: EncryptedRequest, request: Request, response: Response, db: DB) -> UserView:
    limit_login(request)
    payload = decrypt_payload(envelope, request, LoginInput)
    user, token = service.login(payload, read_cookie(request), db)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=service.SESSION_SECONDS,
        httponly=True,
        secure=Settings().auth_cookie_secure,
        samesite="lax",
        path="/api",
    )
    return user


@router.get("/me", response_model=UserView)
def me(user: Annotated[UserAccount, Depends(require_user)]) -> UserView:
    return UserView.model_validate(user)


@router.post("/logout", status_code=204, dependencies=[Depends(check_origin)])
def logout(request: Request, response: Response, db: DB) -> None:
    service.logout(read_cookie(request), db)
    response.delete_cookie(
        COOKIE_NAME,
        path="/api",
        httponly=True,
        secure=Settings().auth_cookie_secure,
        samesite="lax",
    )
