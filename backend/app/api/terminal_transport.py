"""WebSocket transport adapter. Business authorization is supplied by the router."""

import asyncio
import re
from time import monotonic
from urllib.parse import urlsplit

from fastapi import Request, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import COOKIE_NAME, Settings
from app.core.errors import AppError
from app.db.session import get_engine
from app.modules.auth import service as auth_service


async def serve(websocket: WebSocket, authorize, read, write, schema):
    if not local_origin(websocket.headers.get("origin")):
        await websocket.close(code=1008)
        return
    cookie = websocket.cookies.get(COOKIE_NAME, "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", cookie):
        await websocket.close(code=1008)
        return
    position = websocket.query_params.get("cursor", "0")
    if not re.fullmatch(r"[0-9]{1,16}", position) or int(position) > 2**53 - 1:
        await websocket.close(code=1008)
        return

    def check():
        with Session(get_engine(), expire_on_commit=False) as db:
            actor = auth_service.authenticate(cookie, db)
            return authorize(actor, db)

    try:
        bound = await asyncio.to_thread(check)
    except (AppError, SQLAlchemyError):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    cursor, checked, last_state = int(position), monotonic(), None
    attached = False

    async def receive():
        nonlocal cursor
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                raise ValueError("invalid_message")
            if message.get("type") == "attach":
                # Kept for old clients; the authenticated connection fixes its cursor at open.
                continue
            if not attached or bound["session"]["status"] not in ("QUEUED", "RUNNING"):
                continue
            await asyncio.to_thread(write, bound, schema.model_validate(message))

    async def send():
        nonlocal cursor, checked, bound, last_state, attached
        while True:
            if monotonic() - checked >= 2:
                refreshed = await asyncio.to_thread(check)
                if refreshed.get("identity") != bound.get("identity"):
                    await websocket.send_json({"type": "state", "session": refreshed["session"]})
                    return
                bound = refreshed
                checked = monotonic()
            if last_state != bound["session"]:
                # Report a failed/completed native turn immediately, including
                # while a large historical screen is still being replayed.
                await websocket.send_json({"type": "state", "session": bound["session"]})
                last_state = dict(bound["session"])
            page = await asyncio.to_thread(read, bound, cursor)
            cursor = page["next_cursor"]
            if page["chunks"]:
                frame = {"type": "output", "chunks": page["chunks"]}
                if page.get("resizes"):
                    frame["resizes"] = page["resizes"]
                await websocket.send_json(frame)
            if not page["has_more"]:
                if not attached:
                    # Replaying old terminal queries must not send their replies back
                    # to the live PTY. The renderer enables stdin only after parsing.
                    await websocket.send_json({"type": "ready"})
                    attached = True
                if bound["session"]["status"] not in ("QUEUED", "RUNNING"):
                    return
            await asyncio.sleep(0.01 if page["has_more"] else 0.08)

    receiver, sender = asyncio.create_task(receive()), asyncio.create_task(send())
    try:
        done, _ = await asyncio.wait((receiver, sender), return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except (
        AppError,
        ValidationError,
        ValueError,
        WebSocketDisconnect,
        OSError,
        SQLAlchemyError,
        asyncio.CancelledError,
    ):
        pass
    finally:
        receiver.cancel()
        sender.cancel()
        try:
            await asyncio.gather(receiver, sender, return_exceptions=True)
        except asyncio.CancelledError:
            pass
        try:
            await websocket.close()
        except (RuntimeError, WebSocketDisconnect, asyncio.CancelledError):
            pass


def local_origin(origin):
    return origin in Settings().auth_allowed_origins and urlsplit(origin).hostname in (
        "127.0.0.1",
        "localhost",
        "::1",
    )


def check_terminal_origin(request: Request):
    if not local_origin(request.headers.get("origin")):
        raise AppError(403, "origin_not_allowed")
