from logging.config import fileConfig

from sqlalchemy import create_engine

from alembic import context
from app.config import settings
from app.db import configure_sqlite
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    """Where to migrate.

    Normally the app's own settings, but a caller may pass a URL explicitly —
    scripts/export_schema.py migrates a throwaway SQLite file regardless of what
    the app is configured for, and the settings object is a singleton built at
    import time, so an environment variable set later would come too late.
    """
    return config.get_main_option("sqlalchemy.url", None) or settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # configure_sqlite gives SQLite foreign keys and transactional DDL, so a
    # migration that fails halfway rolls back instead of leaving a half-built schema.
    engine = configure_sqlite(create_engine(database_url(), future=True))
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
