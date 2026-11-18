from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import NullPool

from app.core.config import Settings

CONNECTION_OPTIONS = {
    "connect_timeout": 3,
    "keepalives": 1,
    "keepalives_idle": 10,
    "keepalives_interval": 5,
    "keepalives_count": 3,
    "tcp_user_timeout": 15000,
}


class Base(DeclarativeBase):
    """Confirmed business models will register with this metadata."""


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(
        Settings().database_url.get_secret_value(),
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args=dict(CONNECTION_OPTIONS),
    )


@lru_cache(maxsize=1)
def get_scheduler_engine() -> Engine:
    # A session advisory lock must never be returned to the business pool.
    return create_engine(
        Settings().database_url.get_secret_value(),
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={
            **CONNECTION_OPTIONS,
            "application_name": "test-verity-scheduler",
        },
    )


def get_db() -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


def check_database() -> None:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
