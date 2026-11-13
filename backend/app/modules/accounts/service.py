from datetime import UTC, datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import UserAccount, UserSession
from app.modules.accounts.schemas import (
    AccountPage,
    AccountView,
    PasswordInput,
    UserCreate,
    UserUpdate,
)
from app.security.passwords import hash_password


def lock_admin_operation(db: Session, actor: UserAccount) -> None:
    # Serialize rare account writes, including first-admin initialization, so the
    # last administrator cannot be concurrently removed by separate requests.
    db.execute(text("SELECT pg_advisory_xact_lock(2026091101)"))
    db.refresh(actor)
    if actor.status != "ACTIVE" or actor.platform_role != "ADMIN":
        raise AppError(403, "admin_required")


def find_account(db: Session, user_id: int) -> UserAccount:
    account = db.scalar(
        select(UserAccount)
        .where(UserAccount.id == user_id, UserAccount.status != "DELETED")
        .with_for_update()
    )
    if account is None:
        raise AppError(404, "user_not_found")
    return account


def revoke_sessions(db: Session, user_id: int) -> None:
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def commit_account(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "login_name_unavailable") from None


def ensure_other_admin(db: Session, user_id: int) -> None:
    if not db.scalar(
        select(UserAccount.id)
        .where(
            UserAccount.id != user_id,
            UserAccount.platform_role == "ADMIN",
            UserAccount.status == "ACTIVE",
        )
        .limit(1)
    ):
        raise AppError(409, "last_admin_required")


def list_accounts(admin: UserAccount, db: Session, page: int = 1, search: str = "") -> AccountPage:
    filters = [UserAccount.status != "DELETED"]
    if search.strip():
        filters.append(
            UserAccount.login_name.icontains(search.strip(), autoescape=True)
            | UserAccount.display_name.icontains(search.strip(), autoescape=True)
        )
    total = db.scalar(select(func.count()).select_from(UserAccount).where(*filters)) or 0
    accounts = db.scalars(
        select(UserAccount)
        .where(*filters)
        .order_by(UserAccount.id)
        .offset((page - 1) * 20)
        .limit(20)
    )
    return AccountPage(items=[AccountView.model_validate(item) for item in accounts], total=total)


def create_account(payload: UserCreate, admin: UserAccount, db: Session) -> AccountView:
    lock_admin_operation(db, admin)
    account = UserAccount(
        **payload.model_dump(exclude={"password", "confirm_password"}),
        password_hash=hash_password(payload.password.get_secret_value()),
        created_by=admin.id,
        updated_by=admin.id,
    )
    db.add(account)
    commit_account(db)
    return AccountView.model_validate(account)


def edit_account(user_id: int, payload: UserUpdate, admin: UserAccount, db: Session) -> AccountView:
    lock_admin_operation(db, admin)
    account = find_account(db, user_id)
    if account.updated_at != payload.updated_at:
        raise AppError(409, "account_changed")
    losing_admin = payload.platform_role != "ADMIN" or payload.status != "ACTIVE"
    if account.id == admin.id and losing_admin:
        raise AppError(409, "cannot_disable_self")
    if account.platform_role == "ADMIN" and account.status == "ACTIVE" and losing_admin:
        ensure_other_admin(db, account.id)
    revoke = (
        account.login_name != payload.login_name
        or account.platform_role != payload.platform_role
        or account.status != payload.status
    )
    for key, value in payload.model_dump(exclude={"updated_at"}).items():
        setattr(account, key, value)
    account.updated_by = admin.id
    account.updated_at = datetime.now(UTC)
    if revoke:
        revoke_sessions(db, account.id)
    commit_account(db)
    return AccountView.model_validate(account)


def delete_account(user_id: int, admin: UserAccount, db: Session) -> None:
    lock_admin_operation(db, admin)
    account = find_account(db, user_id)
    if account.id == admin.id:
        raise AppError(409, "cannot_delete_self")
    if account.platform_role == "ADMIN" and account.status == "ACTIVE":
        ensure_other_admin(db, account.id)
    account.status = "DELETED"
    account.deleted_at = datetime.now(UTC)
    account.updated_by = admin.id
    revoke_sessions(db, account.id)
    db.commit()


def reset_password(user_id: int, payload: PasswordInput, admin: UserAccount, db: Session) -> None:
    lock_admin_operation(db, admin)
    account = find_account(db, user_id)
    account.password_hash = hash_password(payload.password.get_secret_value())
    account.failed_login_count = 0
    account.locked_until = None
    account.updated_by = admin.id
    revoke_sessions(db, account.id)
    db.commit()
