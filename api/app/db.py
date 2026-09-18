from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

try:
    import psycopg  # noqa: F401
except ImportError as exc:  # pragma: no cover - a setup mistake, not a code path
    # The driver is an extra because the bundled build has no Termux-compatible
    # wheel. Say which command fixes it, rather than surfacing a SQLAlchemy
    # stack trace from the first query.
    raise ImportError(
        "psycopg is not installed. Run `uv sync --extra binary` "
        "(or `--extra system` on Termux, where the bundled libpq has no wheel), "
        "or just run ./scripts/setup.sh."
    ) from exc

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
