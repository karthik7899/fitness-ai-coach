"""Health Connect ingestion, via its scheduled export on Google Drive.

Health Connect is on-device and has no cloud API, and the Google Fit REST API it
replaced is closed to new developers and shuts down at the end of 2026. The route
that needs no Android app: Android Settings -> Health Connect -> Backup and
restore -> schedule an export to Google Drive. That drops a ZIP containing a
SQLite database, which this adapter polls, unpacks and normalises. Watch data
(Da Fit and anything else writing to Health Connect) arrives the same way.

The export's internal schema is Health Connect's own and shifts between Android
versions, so extraction is schema-discovering: table and column names below are
candidate lists, and `inspect_export` prints what a real export actually contains.
"""

from __future__ import annotations

import datetime as dt
import io
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.adapters.base import SyncOutcome, content_hash, get_token, save_token, store_raw, sync_run
from app.config import settings
from app.models import (
    METRIC_BODY_WEIGHT_KG,
    METRIC_HRV_MS,
    METRIC_RESTING_HR,
    METRIC_SLEEP_MINUTES,
    METRIC_STEPS,
    DailyMetric,
)

SOURCE = "health_connect"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
EXPORT_QUERY = "name contains 'Health Connect' and trashed = false"


@dataclass(frozen=True)
class RecordSpec:
    """How to pull one metric out of the export database."""

    metric: str
    unit: str
    tables: tuple[str, ...]
    value_columns: tuple[str, ...]
    start_columns: tuple[str, ...] = ("start_time", "time", "epoch_millis")
    end_columns: tuple[str, ...] = ()
    aggregate: str = "sum"  # sum | mean | duration_minutes
    scale: float = 1.0
    bucket_on_end: bool = False


SPECS: tuple[RecordSpec, ...] = (
    RecordSpec(
        metric=METRIC_STEPS,
        unit="count",
        tables=("steps_record_table",),
        value_columns=("count",),
        end_columns=("end_time",),
    ),
    # Bucketed on wake time: a sleep session starting Monday night is Tuesday's sleep.
    RecordSpec(
        metric=METRIC_SLEEP_MINUTES,
        unit="min",
        tables=("sleep_session_record_table",),
        value_columns=(),
        end_columns=("end_time",),
        aggregate="duration_minutes",
        bucket_on_end=True,
    ),
    RecordSpec(
        metric=METRIC_RESTING_HR,
        unit="bpm",
        tables=("resting_heart_rate_record_table",),
        value_columns=("beats_per_minute",),
        aggregate="mean",
    ),
    RecordSpec(
        metric=METRIC_HRV_MS,
        unit="ms",
        tables=("heart_rate_variability_rmssd_record_table",),
        value_columns=("heart_rate_variability_millis", "heart_rate_variability"),
        aggregate="mean",
    ),
    RecordSpec(
        metric=METRIC_BODY_WEIGHT_KG,
        unit="kg",
        tables=("weight_record_table",),
        value_columns=("weight",),
        aggregate="mean",
        scale=0.001,  # Health Connect stores mass in grams.
    ),
)


# --------------------------------------------------------------------------
# Google Drive
# --------------------------------------------------------------------------


def _credentials(session: Session):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    stored = get_token(session, SOURCE)
    creds = Credentials.from_authorized_user_info(stored, SCOPES) if stored else None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not settings.google_credentials_path.exists():
            raise RuntimeError(
                f"{settings.google_credentials_path} not found. Download a desktop OAuth "
                "client from Google Cloud Console and save it there."
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            str(settings.google_credentials_path), SCOPES
        )
        creds = flow.run_local_server(port=0, prompt="consent")

    save_token(session, SOURCE, {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
    })
    return creds


def is_connected(session: Session) -> bool:
    return get_token(session, SOURCE) is not None


def download_latest_export(session: Session) -> tuple[str, bytes] | None:
    service = build("drive", "v3", credentials=_credentials(session))
    listing = (
        service.files()
        .list(
            q=EXPORT_QUERY,
            spaces="drive",
            orderBy="modifiedTime desc",
            pageSize=5,
            fields="files(id, name, modifiedTime, size)",
        )
        .execute()
    )
    files = listing.get("files", [])
    if not files:
        return None

    newest = files[0]
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(
        buffer, service.files().get_media(fileId=newest["id"])
    )
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return newest["name"], buffer.getvalue()


def _unpack(archive: bytes) -> Path:
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        db_names = [n for n in zf.namelist() if n.endswith(".db")]
        if not db_names:
            raise RuntimeError(f"No .db inside the export archive: {zf.namelist()}")
        target = Path(tempfile.mkdtemp(prefix="hc_export_")) / "export.db"
        target.write_bytes(zf.read(db_names[0]))
    return target


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]


def _pick(available: list[str], candidates: tuple[str, ...]) -> str | None:
    lowered = {c.lower(): c for c in available}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def inspect_export(db_path: Path) -> dict:
    """Report the export's structure, and which specs can bind to it."""
    with sqlite3.connect(db_path) as conn:
        present = _tables(conn)
        report: dict = {"tables": sorted(present), "specs": {}}
        for spec in SPECS:
            table = _pick(sorted(present), spec.tables)
            entry: dict = {"table": table}
            if table:
                cols = _columns(conn, table)
                entry["columns"] = cols
                entry["value_column"] = _pick(cols, spec.value_columns)
                entry["start_column"] = _pick(cols, spec.start_columns)
                entry["end_column"] = _pick(cols, spec.end_columns)
                entry["rows"] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            report["specs"][spec.metric] = entry
    return report


def _to_local_date(epoch_millis: int) -> dt.date:
    return dt.datetime.fromtimestamp(epoch_millis / 1000).date()


def extract_daily(db_path: Path) -> dict[tuple[dt.date, str], tuple[float, str]]:
    """Reduce the export to {(date, metric): (value, unit)}."""
    buckets: dict[tuple[dt.date, str], list[float]] = {}
    units: dict[str, str] = {}

    with sqlite3.connect(db_path) as conn:
        present = sorted(_tables(conn))
        for spec in SPECS:
            table = _pick(present, spec.tables)
            if table is None:
                continue

            cols = _columns(conn, table)
            start_col = _pick(cols, spec.start_columns)
            end_col = _pick(cols, spec.end_columns) if spec.end_columns else None
            value_col = _pick(cols, spec.value_columns) if spec.value_columns else None

            if start_col is None:
                continue
            if spec.aggregate == "duration_minutes" and end_col is None:
                continue
            if spec.aggregate != "duration_minutes" and value_col is None:
                continue

            selected = [f'"{start_col}"']
            if end_col:
                selected.append(f'"{end_col}"')
            if value_col:
                selected.append(f'"{value_col}"')

            for row in conn.execute(f'SELECT {", ".join(selected)} FROM "{table}"'):
                start_ms = row[0]
                if start_ms is None:
                    continue
                offset = 1
                end_ms = row[offset] if end_col else None
                if end_col:
                    offset += 1
                raw_value = row[offset] if value_col else None

                if spec.aggregate == "duration_minutes":
                    if end_ms is None:
                        continue
                    value = (end_ms - start_ms) / 60000.0
                else:
                    if raw_value is None:
                        continue
                    value = float(raw_value) * spec.scale

                anchor = end_ms if (spec.bucket_on_end and end_ms is not None) else start_ms
                buckets.setdefault((_to_local_date(anchor), spec.metric), []).append(value)
                units[spec.metric] = spec.unit

    result: dict[tuple[dt.date, str], tuple[float, str]] = {}
    for (day, metric), values in buckets.items():
        spec = next(s for s in SPECS if s.metric == metric)
        total = sum(values) / len(values) if spec.aggregate == "mean" else sum(values)
        result[(day, metric)] = (round(total, 3), units[metric])
    return result


def _upsert_metrics(session: Session, daily: dict[tuple[dt.date, str], tuple[float, str]]) -> int:
    written = 0
    for (day, metric), (value, unit) in daily.items():
        stmt = (
            pg_insert(DailyMetric)
            .values(
                date=day, metric=metric, source=SOURCE, value=Decimal(str(value)), unit=unit
            )
            .on_conflict_do_update(
                index_elements=[DailyMetric.date, DailyMetric.metric, DailyMetric.source],
                set_={"value": Decimal(str(value)), "unit": unit},
            )
        )
        session.execute(stmt)
        written += 1
    return written


def sync(session: Session) -> SyncOutcome:
    with sync_run(session, SOURCE) as outcome:
        downloaded = download_latest_export(session)
        if downloaded is None:
            raise RuntimeError(
                "No Health Connect export found on Drive. Enable the scheduled export "
                "in Android Settings -> Health Connect -> Backup and restore."
            )

        filename, archive = downloaded
        fingerprint = content_hash({"name": filename, "sha": content_hash(archive.hex())})
        raw_id = store_raw(
            session,
            SOURCE,
            "export_file",
            {"name": filename, "bytes": len(archive), "fingerprint": fingerprint},
            external_id=filename,
        )
        if raw_id is None:
            # Same archive as last time; Drive has not received a fresh export yet.
            session.commit()
            return outcome

        db_path = _unpack(archive)
        daily = extract_daily(db_path)
        outcome.read = len(daily)
        outcome.written = _upsert_metrics(session, daily)
        session.commit()
        return outcome
