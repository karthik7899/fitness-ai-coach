"""Backup and restore for the SQLite database.

The whole training history is one file. On a phone that file lives on a device
that gets lost, wiped and replaced; on a desktop it is one `rm` from gone. A
backup that turns out to be unreadable is worse than none, so nothing here
reports success without opening the result and looking at it.

The format is the database itself, which anything that speaks SQLite can read —
including the Android app, whose schema is generated from these same
migrations. A backup is how history moves between the two.
"""

from __future__ import annotations

import datetime as dt
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import Engine

# Tables a file must have before it is treated as an Aura backup.
REQUIRED_TABLES = ("exercises", "workouts", "sets", "daily_metrics", "exercise_muscles")


class NotABackup(ValueError):
    """The file is not a restorable Aura database, with the reason why."""


@dataclass
class BackupInfo:
    workouts: int
    sets: int
    exercises: int
    daily_metrics: int
    earliest: str | None
    latest: str | None

    @property
    def is_empty(self) -> bool:
        return self.workouts == 0 and self.sets == 0 and self.daily_metrics == 0


def database_path(engine: Engine) -> Path:
    """The file behind a SQLite engine, or a refusal for anything else."""
    if engine.dialect.name != "sqlite":
        raise NotABackup(
            "Backups are for the SQLite database. This app is pointed at "
            f"{engine.dialect.name}, whose own tools do this better — pg_dump for PostgreSQL."
        )
    path = engine.url.database
    if not path or path == ":memory:":
        raise NotABackup("This database is in memory; there is no file to back up.")
    return Path(path)


def describe(connection: sqlite3.Connection) -> BackupInfo:
    def count(table: str) -> int:
        return connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

    earliest, latest = connection.execute(
        "SELECT MIN(performed_on), MAX(performed_on) FROM workouts"
    ).fetchone()

    return BackupInfo(
        workouts=count("workouts"),
        sets=count("sets"),
        exercises=count("exercises"),
        daily_metrics=count("daily_metrics"),
        earliest=earliest,
        latest=latest,
    )


def verify(path: Path) -> BackupInfo:
    """Check a file is a readable Aura database, and say what is in it."""
    if not path.exists() or path.stat().st_size == 0:
        raise NotABackup("The file is empty.")

    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise NotABackup(f"The file is a damaged database ({integrity}).")

            present = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
                )
            }
            missing = [t for t in REQUIRED_TABLES if t not in present]
            if missing:
                raise NotABackup(
                    "This is a SQLite file but not an Aura backup: "
                    f"no {', '.join(missing)}."
                )
            return describe(connection)
    except sqlite3.DatabaseError as exc:
        raise NotABackup(f"The file is not a SQLite database ({exc}).") from exc


def create(engine: Engine, destination: Path) -> BackupInfo:
    """Write a consistent copy of the live database to `destination`."""
    source = database_path(engine)

    with engine.connect() as connection:
        # Flush the write-ahead log into the main file. Without this a copy can
        # be missing the most recent writes — which are the ones a backup is
        # usually being taken for.
        connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return verify(destination)


def suggested_name(now: dt.datetime | None = None) -> str:
    stamp = (now or dt.datetime.now()).strftime("%Y-%m-%d-%H%M")
    return f"aura-backup-{stamp}.db"


def restore(engine: Engine, candidate: Path) -> tuple[BackupInfo, Path]:
    """Replace the live database with `candidate`, keeping what was there.

    The incoming file is verified first, and the database it replaces is moved
    aside rather than deleted, so restoring the wrong file is recoverable.
    Returns what was restored and where the previous database went.
    """
    info = verify(candidate)
    target = database_path(engine)

    # Drop pooled connections so nothing keeps writing to the file being moved.
    engine.dispose()

    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    replaced = target.with_name(f"{target.name}.replaced-{stamp}")
    if target.exists():
        shutil.move(str(target), str(replaced))
    # The sidecars belong to the database being replaced, not the new one.
    for suffix in ("-wal", "-shm"):
        sidecar = target.with_name(target.name + suffix)
        if sidecar.exists():
            sidecar.unlink()

    try:
        shutil.copy2(candidate, target)
    except OSError:
        if replaced.exists():
            shutil.move(str(replaced), str(target))
        raise

    return info, replaced
