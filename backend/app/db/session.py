from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session

from app.core.config import Settings


class Base(DeclarativeBase):
    """Confirmed business models will register with this metadata."""


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(
        Settings().database_url.get_secret_value(),
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"connect_timeout": 3},
    )


def get_db() -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


def check_database() -> None:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
