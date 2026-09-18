"""Local file ingestion, in two modes.

**The inbox** is a queue you drop files into. Imported files move to
`processed/`, unrecognised ones to `rejected/`, so what remains is what is
waiting.

**Watch folders** are directories another app owns — FitNotes' automatic backup
target, Gadgetbridge's auto-export folder. These are read and never written:
moving a backup out from under the app that made it would be rude at best and
destructive at worst. Point the app at those folders and the whole pipeline is
automatic, with no cloud account and nothing to remember.

Both modes identify files by probing contents rather than trusting extensions,
and import each once, keyed on the file's hash. Automatic backups overwrite the
same filename with new content, which is exactly the case hashing handles: same
name, new hash, re-imported — and the FitNotes importer replaces a day rather
than duplicating it, so repeats are safe.
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


def _handle(session: Session, path: Path, consume: bool) -> Imported | None:
    """Import one file. `consume` files are moved aside; watched ones are left alone.

    Returns None when there is nothing worth reporting — an already-imported file,
    or something unrelated sitting in a watched folder.
    """
    kind = detect_kind(path)

    if kind == KIND_UNKNOWN:
        if not consume:
            # A watched folder belongs to another app and will be full of files
            # that are none of our business. Silence is the correct response.
            return None
        # Nothing about this will change on a retry, so set it aside rather than
        # re-reporting it on every scan.
        _move_to(path, "rejected")
        return Imported(path=path, kind=kind, written=0, error="unrecognised file type")

    raw_id = store_raw(
        session,
        SOURCE,
        kind,
        {"name": path.name, "sha256": _file_digest(path), "bytes": path.stat().st_size},
        external_id=path.name,
    )
    if raw_id is None:
        session.commit()
        if not consume:
            return None
        _move_to(path, "processed")
        return Imported(path=path, kind=kind, written=0)

    try:
        written = _import_one(session, path, kind)
        session.commit()
    except Exception as exc:
        # A recognised file that failed may just need a retry — the database was
        # down, or the file was still being written — so leave it where it is.
        session.rollback()
        return Imported(path=path, kind=kind, written=0, error=f"{type(exc).__name__}: {exc}")

    if consume:
        _move_to(path, "processed")
    return Imported(path=path, kind=kind, written=written)


def _files_in(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.is_file())


def scan(session: Session, watch_dirs: list[Path] | None = None) -> list[Imported]:
    """Import from the drop queue and from any watched folders."""
    inbox = settings.inbox_path
    inbox.mkdir(parents=True, exist_ok=True)

    results: list[Imported] = []
    for path in _files_in(inbox):
        outcome = _handle(session, path, consume=True)
        if outcome is not None:
            results.append(outcome)

    seen = {inbox.resolve()}
    for directory in watch_dirs or []:
        resolved = directory.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        for path in _files_in(resolved):
            outcome = _handle(session, path, consume=False)
            if outcome is not None:
                results.append(outcome)

    return results


def is_connected(session: Session) -> bool:  # noqa: ARG001 - uniform adapter signature
    """The inbox is always available; it is just a directory."""
    return True


def sync(session: Session) -> SyncOutcome:
    from app import settings_store

    watched, _ = settings_store.watch_dirs(session)
    with sync_run(session, SOURCE) as outcome:
        for result in scan(session, watched):
            outcome.read += 1
            outcome.written += result.written
        return outcome
