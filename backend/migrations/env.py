from alembic import context

from app.core.config import Settings
from app.db.models import UserAccount, UserSession  # noqa: F401
from app.db.session import Base, get_engine

target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(
        url=Settings().database_url.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
