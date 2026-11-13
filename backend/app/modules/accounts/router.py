from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import DB, Admin, check_origin
from app.api.encryption import EncryptedRequest, decrypt_payload
from app.modules.accounts import service
from app.modules.accounts.schemas import (
    AccountPage,
    AccountView,
    PasswordInput,
    UserCreate,
    UserUpdate,
)

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=AccountPage)
def list_accounts(
    admin: Admin,
    db: DB,
    page: Annotated[int, Query(ge=1, le=100000)] = 1,
    search: Annotated[str, Query(max_length=80)] = "",
) -> AccountPage:
    return service.list_accounts(admin, db, page, search)


@router.post("", response_model=AccountView, status_code=201, dependencies=[Depends(check_origin)])
def create_account(
    envelope: EncryptedRequest, request: Request, admin: Admin, db: DB
) -> AccountView:
    payload = decrypt_payload(envelope, request, UserCreate)
    return service.create_account(payload, admin, db)


@router.patch("/{user_id}", response_model=AccountView, dependencies=[Depends(check_origin)])
def edit_account(user_id: int, payload: UserUpdate, admin: Admin, db: DB) -> AccountView:
    return service.edit_account(user_id, payload, admin, db)


@router.delete("/{user_id}", status_code=204, dependencies=[Depends(check_origin)])
def delete_account(user_id: int, admin: Admin, db: DB) -> None:
    return service.delete_account(user_id, admin, db)


@router.post("/{user_id}/reset-password", status_code=204, dependencies=[Depends(check_origin)])
def reset_password(
    user_id: int, envelope: EncryptedRequest, request: Request, admin: Admin, db: DB
) -> None:
    payload = decrypt_payload(envelope, request, PasswordInput)
    return service.reset_password(user_id, payload, admin, db)
