from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


def _require_driver(url: str) -> None:
    """Fail with the command that fixes it, rather than a driver stack trace.

    psycopg is an optional extra: a SQLite install needs no driver at all, and
    on Termux the bundled build has no wheel, so it is installed against the
    system libpq instead.
    """
    if url.startswith("sqlite"):
        return
    try:
        import psycopg  # noqa: F401
    except ImportError as exc:  # pragma: no cover - a setup mistake, not a code path
        raise ImportError(
            "psycopg is not installed, but DATABASE_URL points at PostgreSQL. "
            "Run `uv sync --extra binary` (or `--extra system` on Termux, where "
            "the bundled libpq has no wheel), or just run ./scripts/setup.sh."
        ) from exc


def configure_sqlite(engine: Engine) -> Engine:
    """Make SQLite behave like a real transactional database.

    Two defaults have to be corrected. Foreign keys are off unless asked for, so
    `ON DELETE CASCADE` silently does nothing — deleting a workout would strand
    its sets. And pysqlite manages transactions implicitly in a way that breaks
    SAVEPOINT and transactional DDL, so BEGIN is issued explicitly instead.
    """
    if engine.dialect.name != "sqlite":
        return engine

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _on_begin(connection):
        connection.exec_driver_sql("BEGIN")

    return engine


_require_driver(settings.database_url)

engine = configure_sqlite(
    create_engine(settings.database_url, pool_pre_ping=True, future=True)
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
