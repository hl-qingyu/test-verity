import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import UserAccount, UserSession
from app.modules.auth.schemas import LoginInput, UserView
from app.security.passwords import hash_password, token_hash, verify_password

SESSION_SECONDS = 8 * 60 * 60
_dummy_password_hash = hash_password(secrets.token_urlsafe(32))


def authenticate(token: str | None, db: Session) -> UserAccount:
    if token is None:
        raise AppError(401, "not_authenticated")
    user = db.scalar(
        select(UserAccount)
        .join(UserSession, UserSession.user_id == UserAccount.id)
        .where(
            UserSession.token_hash == token_hash(token),
            UserSession.expires_at > datetime.now(UTC),
            UserSession.revoked_at.is_(None),
            UserAccount.status == "ACTIVE",
        )
    )
    if user is None:
        raise AppError(401, "not_authenticated")
    return user


def login(payload: LoginInput, previous_token: str | None, db: Session) -> tuple[UserView, str]:
    user = db.scalar(
        select(UserAccount).where(UserAccount.login_name == payload.login_name).with_for_update()
    )
    now = datetime.now(UTC)
    valid = verify_password(
        payload.password.get_secret_value(),
        user.password_hash if user else _dummy_password_hash,
    )
    if user is None or user.status != "ACTIVE":
        raise AppError(401, "invalid_credentials")
    if user.locked_until and user.locked_until > now:
        raise AppError(429, "too_many_attempts", headers={"Retry-After": "900"})
    if user.locked_until:
        user.failed_login_count = 0
        user.locked_until = None
    if not valid:
        user.failed_login_count += 1
        if user.failed_login_count >= 5:
            user.locked_until = now + timedelta(minutes=15)
        db.commit()
        raise AppError(401, "invalid_credentials")
    user.failed_login_count = 0
    user.locked_until = None
    if previous_token:
        db.execute(
            update(UserSession)
            .where(
                UserSession.token_hash == token_hash(previous_token),
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=token_hash(token),
            expires_at=now + timedelta(seconds=SESSION_SECONDS),
        )
    )
    db.commit()
    return UserView.model_validate(user), token


def logout(token: str | None, db: Session) -> None:
    if token:
        db.execute(
            update(UserSession)
            .where(UserSession.token_hash == token_hash(token), UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        db.commit()
