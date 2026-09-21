from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app import backup
from app.db import engine

router = APIRouter(prefix="/api/backup", tags=["backup"])


def _info(value: backup.BackupInfo) -> dict:
    return {
        "workouts": value.workouts,
        "sets": value.sets,
        "exercises": value.exercises,
        "daily_metrics": value.daily_metrics,
        "earliest": value.earliest,
        "latest": value.latest,
        "is_empty": value.is_empty,
    }


@router.get("")
def download() -> FileResponse:
    """Download a consistent copy of the database."""
    temporary = Path(tempfile.mkdtemp(prefix="aura-backup-")) / backup.suggested_name()
    try:
        backup.create(engine, temporary)
    except backup.NotABackup as exc:
        shutil.rmtree(temporary.parent, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return FileResponse(
        temporary,
        media_type="application/vnd.sqlite3",
        filename=temporary.name,
        # The copy only has to survive being sent.
        background=BackgroundTask(shutil.rmtree, temporary.parent, ignore_errors=True),
    )


def _receive(upload: UploadFile) -> Path:
    incoming = Path(tempfile.mkdtemp(prefix="aura-restore-")) / "candidate.db"
    with incoming.open("wb") as handle:
        shutil.copyfileobj(upload.file, handle)
    return incoming


@router.post("/inspect")
def inspect(file: UploadFile) -> dict:
    """Say what is in a backup without touching the live database."""
    incoming = _receive(file)
    try:
        return _info(backup.verify(incoming))
    except backup.NotABackup as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        shutil.rmtree(incoming.parent, ignore_errors=True)


@router.post("/restore")
def restore(file: UploadFile) -> dict:
    """Replace the live database with an uploaded backup.

    The current database is moved aside rather than deleted, so restoring the
    wrong file is recoverable.
    """
    incoming = _receive(file)
    try:
        info, replaced = backup.restore(engine, incoming)
    except backup.NotABackup as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        shutil.rmtree(incoming.parent, ignore_errors=True)

    return {"restored": _info(info), "previous_database": str(replaced)}
