"""Local file-drop ingestion.

Drop a FitNotes backup or a Gadgetbridge export into the inbox directory and the
scheduler picks it up — no cloud account in the path. Sync the folder from your
phone with Syncthing, or copy over USB; the app only ever reads a local
directory.

Files are identified by probing their contents rather than trusting the
extension, imported once (keyed on the file's hash, so re-dropping the same
backup is a no-op), and then moved into `processed/` so the inbox stays a queue.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.adapters import fitnotes, gadgetbridge, health_connect
from app.adapters.base import SyncOutcome, store_raw, sync_run
from app.config import settings

SOURCE = "inbox"

KIND_FITNOTES_DB = "fitnotes_db"
KIND_FITNOTES_CSV = "fitnotes_csv"
KIND_GADGETBRIDGE = "gadgetbridge"
KIND_HEALTH_CONNECT = "health_connect_zip"
KIND_UNKNOWN = "unknown"


@dataclass
class Imported:
    path: Path
    kind: str
    written: int
    error: str | None = None


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sqlite_tables(path: Path) -> set[str]:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.Error:
        return set()


def detect_kind(path: Path) -> str:
    """Identify a dropped file by its contents, not its extension."""
    suffix = path.suffix.lower()
    if suffix == ".zip":
        return KIND_HEALTH_CONNECT
    if suffix == ".csv":
        return KIND_FITNOTES_CSV

    tables = {t.lower() for t in _sqlite_tables(path)}
    if not tables:
        return KIND_UNKNOWN
    if {"training_log", "exercise"} <= tables:
        return KIND_FITNOTES_DB
    if any(t.endswith("activity_sample") for t in tables):
        return KIND_GADGETBRIDGE
    return KIND_UNKNOWN


def _import_one(session: Session, path: Path, kind: str) -> int:
    if kind == KIND_FITNOTES_DB:
        return fitnotes.import_sets(session, fitnotes.parse_sqlite(path)).written
    if kind == KIND_FITNOTES_CSV:
        return fitnotes.import_sets(session, fitnotes.parse_csv(path.read_bytes())).written
    if kind == KIND_GADGETBRIDGE:
        return gadgetbridge.upsert_daily(session, gadgetbridge.extract_daily(path))
    if kind == KIND_HEALTH_CONNECT:
        unpacked = health_connect.unpack_export(path.read_bytes())
        return health_connect.upsert_daily(session, health_connect.extract_daily(unpacked))
    raise ValueError(f"Unrecognised file: {path.name}")


def _move_to(path: Path, folder: str) -> None:
    destination = settings.inbox_path / folder
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / path.name
    if target.exists():
        target = destination / f"{path.stem}-{path.stat().st_mtime_ns}{path.suffix}"
    shutil.move(str(path), str(target))


def scan(session: Session) -> list[Imported]:
    """Import every file waiting in the inbox. Returns one result per file."""
    inbox = settings.inbox_path
    inbox.mkdir(parents=True, exist_ok=True)

    results: list[Imported] = []
    for path in sorted(p for p in inbox.iterdir() if p.is_file()):
        kind = detect_kind(path)

        # Nothing about this file will change on a retry, so set it aside rather
        # than re-reporting it on every scan.
        if kind == KIND_UNKNOWN:
            _move_to(path, "rejected")
            results.append(
                Imported(path=path, kind=kind, written=0, error="unrecognised file type")
            )
            continue

        digest = _file_digest(path)

        # Keyed on the file's own hash, so re-dropping the same backup is a no-op.
        raw_id = store_raw(
            session,
            SOURCE,
            kind,
            {"name": path.name, "sha256": digest, "bytes": path.stat().st_size},
            external_id=path.name,
        )
        if raw_id is None:
            session.commit()
            _move_to(path, "processed")
            results.append(Imported(path=path, kind=kind, written=0))
            continue

        try:
            written = _import_one(session, path, kind)
            session.commit()
        except Exception as exc:
            # A recognised file that failed to import may just need a retry
            # (the database was down, the file was still copying), so leave it.
            session.rollback()
            results.append(
                Imported(path=path, kind=kind, written=0, error=f"{type(exc).__name__}: {exc}")
            )
            continue

        _move_to(path, "processed")
        results.append(Imported(path=path, kind=kind, written=written))

    return results


def is_connected(session: Session) -> bool:  # noqa: ARG001 - uniform adapter signature
    """The inbox is always available; it is just a directory."""
    return True


def sync(session: Session) -> SyncOutcome:
    with sync_run(session, SOURCE) as outcome:
        for result in scan(session):
            outcome.read += 1
            outcome.written += result.written
        return outcome
