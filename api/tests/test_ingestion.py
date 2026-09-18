"""Importers: unit handling, idempotency, and file identification."""

import datetime as dt

import pytest
from sqlalchemy import func, select

from app.adapters import fitnotes, gadgetbridge, inbox
from app.config import Settings
from app.models import SOURCE_FITNOTES, DailyMetric, SetEntry, Workout
from tests.conftest import rows_of, write_fitnotes_db, write_gadgetbridge_db

TODAY = dt.date.today()


def epoch(day: dt.date, hour: int, minute: int = 0) -> int:
    return int(dt.datetime.combine(day, dt.time(hour, minute)).timestamp())


# --------------------------------------------------------------------------
# FitNotes
# --------------------------------------------------------------------------


def test_metric_weight_is_taken_as_kilograms(tmp_path):
    """metric_weight is already metric; the unit flag is a display preference.

    The old app converted it anyway and mislabelled kilograms as pounds.
    """
    path = write_fitnotes_db(
        tmp_path / "b.fitnotes", [(TODAY.isoformat(), "Back Squat", 100.0, 5, 1)]
    )
    parsed = fitnotes.parse_sqlite(path)
    assert len(parsed) == 1
    assert float(parsed[0].weight_kg) == 100.0


def test_csv_converts_pounds_to_kilograms(tmp_path):
    csv = (
        "Date,Exercise,Category,Weight (kg),Weight (lbs),Reps,Distance,Distance Unit,Time,Comment\n"
        f"{TODAY.isoformat()},Overhead Press,Shoulders,,135,5,,,,\n"
    )
    parsed = fitnotes.parse_csv(csv.encode())
    assert float(parsed[0].weight_kg) == pytest.approx(61.235, abs=0.001)


def test_csv_prefers_the_kilogram_column_when_both_are_present(tmp_path):
    csv = (
        "Date,Exercise,Category,Weight (kg),Weight (lbs),Reps,Distance,Distance Unit,Time,Comment\n"
        f"{TODAY.isoformat()},Deadlift,Back,60,132.3,5,,,,\n"
    )
    assert float(fitnotes.parse_csv(csv.encode())[0].weight_kg) == 60.0


def test_rows_without_a_date_or_exercise_are_skipped(tmp_path):
    csv = (
        "Date,Exercise,Category,Weight (kg),Weight (lbs),Reps,Distance,Distance Unit,Time,Comment\n"
        ",Deadlift,Back,60,,5,,,,\n"
        f"{TODAY.isoformat()},,Back,60,,5,,,,\n"
        f"{TODAY.isoformat()},Deadlift,Back,60,,5,,,,\n"
    )
    assert len(fitnotes.parse_csv(csv.encode())) == 1


def test_reimporting_replaces_a_day_rather_than_duplicating(session, tmp_path):
    entries = [
        (TODAY.isoformat(), "Back Squat", 100.0, 5, 0),
        (TODAY.isoformat(), "Back Squat", 100.0, 5, 0),
    ]
    path = write_fitnotes_db(tmp_path / "b.fitnotes", entries)

    first = fitnotes.import_sets(session, fitnotes.parse_sqlite(path))
    second = fitnotes.import_sets(session, fitnotes.parse_sqlite(path))

    assert first.written == second.written == 2
    total = session.scalar(
        select(func.count())
        .select_from(SetEntry)
        .join(Workout)
        .where(Workout.source == SOURCE_FITNOTES)
    )
    assert total == 2, "a second import must not double the day"


def test_import_does_not_touch_manually_logged_sets(session, exercises, tmp_path):
    from tests.conftest import add_workout

    add_workout(session, TODAY, [(exercises["squat"], 120, 3, False)])
    path = write_fitnotes_db(
        tmp_path / "b.fitnotes", [(TODAY.isoformat(), "Back Squat", 100.0, 5, 0)]
    )
    fitnotes.import_sets(session, fitnotes.parse_sqlite(path))

    manual = session.scalar(
        select(func.count()).select_from(SetEntry).join(Workout).where(Workout.source == "manual")
    )
    assert manual == 1, "the imported day must not clobber the manual workout"


def test_a_non_fitnotes_database_is_rejected(tmp_path):
    path = write_gadgetbridge_db(tmp_path / "gb.db", [(epoch(TODAY, 9), 100, 60, 1)])
    with pytest.raises(ValueError, match="Not a FitNotes backup"):
        fitnotes.parse_sqlite(path)


# --------------------------------------------------------------------------
# Gadgetbridge
# --------------------------------------------------------------------------


def test_steps_are_summed_per_day(tmp_path):
    path = write_gadgetbridge_db(
        tmp_path / "gb.db",
        [(epoch(TODAY, 9), 100, 70, 1), (epoch(TODAY, 10), 250, 70, 1)],
    )
    daily = gadgetbridge.extract_daily(path)
    assert daily[(TODAY, "steps")] == 350.0


def test_resting_hr_uses_the_low_end_not_the_single_minimum(tmp_path):
    """One stray low sample should not become the day's resting heart rate."""
    samples = [(epoch(TODAY, 3, m), 0, 70, 1) for m in range(20)]
    samples.append((epoch(TODAY, 4), 0, 31, 1))  # a single outlier
    path = write_gadgetbridge_db(tmp_path / "gb.db", samples)
    assert gadgetbridge.extract_daily(path)[(TODAY, "resting_hr")] == 70.0


def test_implausible_heart_rates_are_ignored(tmp_path):
    path = write_gadgetbridge_db(
        tmp_path / "gb.db",
        [(epoch(TODAY, 9), 0, 0, 1), (epoch(TODAY, 10), 0, 10, 1), (epoch(TODAY, 11), 0, 55, 1)],
    )
    # 0 means "not measured" and 10bpm is noise, so only 55 survives.
    assert gadgetbridge.extract_daily(path)[(TODAY, "resting_hr")] == 55.0


def test_sleep_minutes_come_from_typed_sleep_kinds(tmp_path):
    samples = [(epoch(TODAY, 2, m), 0, 50, 2) for m in range(30)]  # light
    samples += [(epoch(TODAY, 3, m), 0, 48, 4) for m in range(30)]  # deep
    samples += [(epoch(TODAY, 9, m), 0, 80, 1) for m in range(30)]  # awake
    path = write_gadgetbridge_db(tmp_path / "gb.db", samples)
    assert gadgetbridge.extract_daily(path)[(TODAY, "sleep_minutes")] == 60.0


def test_upsert_is_idempotent(session, tmp_path):
    path = write_gadgetbridge_db(tmp_path / "gb.db", [(epoch(TODAY, 9), 500, 60, 1)])
    daily = gadgetbridge.extract_daily(path)
    gadgetbridge.upsert_daily(session, daily)
    gadgetbridge.upsert_daily(session, daily)
    session.flush()

    rows = session.scalars(
        select(DailyMetric).where(DailyMetric.metric == "steps", DailyMetric.date == TODAY)
    ).all()
    assert len(rows) == 1
    assert float(rows[0].value) == 500.0


# --------------------------------------------------------------------------
# Inbox
# --------------------------------------------------------------------------


@pytest.fixture
def inbox_dir(tmp_path, monkeypatch):
    target = tmp_path / "inbox"
    target.mkdir()
    monkeypatch.setattr(Settings, "inbox_path", property(lambda self: target))
    return target


def test_files_are_identified_by_content_not_extension(inbox_dir, tmp_path):
    """A backup saved with the wrong extension still has to be recognised."""
    misnamed = write_fitnotes_db(
        tmp_path / "backup.txt", [(TODAY.isoformat(), "Back Squat", 100.0, 5, 0)]
    )
    assert inbox.detect_kind(misnamed) == inbox.KIND_FITNOTES_DB

    watch = write_gadgetbridge_db(tmp_path / "watch.bin", [(epoch(TODAY, 9), 10, 60, 1)])
    assert inbox.detect_kind(watch) == inbox.KIND_GADGETBRIDGE

    (tmp_path / "notes.txt").write_text("just some notes")
    assert inbox.detect_kind(tmp_path / "notes.txt") == inbox.KIND_UNKNOWN


def test_gadgetbridge_auto_export_has_no_extension(inbox_dir, session):
    """Gadgetbridge's scheduled export is a bare file named `Gadgetbridge`."""
    write_gadgetbridge_db(inbox_dir / "Gadgetbridge", [(epoch(TODAY, 9), 4321, 60, 1)])
    assert inbox.detect_kind(inbox_dir / "Gadgetbridge") == inbox.KIND_GADGETBRIDGE

    result = inbox.scan(session)[0]
    assert result.written > 0
    assert (inbox_dir / "processed" / "Gadgetbridge").exists()


def test_dropped_files_import_and_move_to_processed(session, inbox_dir):
    write_fitnotes_db(
        inbox_dir / "b.fitnotes", [(TODAY.isoformat(), "Back Squat", 100.0, 5, 0)]
    )
    write_gadgetbridge_db(inbox_dir / "w.db", [(epoch(TODAY, 9), 800, 60, 1)])

    results = {r.path.name: r for r in inbox.scan(session)}
    assert results["b.fitnotes"].written == 1
    assert results["w.db"].written > 0
    assert not list(inbox_dir.glob("*.fitnotes")), "imported files should leave the queue"
    assert (inbox_dir / "processed" / "b.fitnotes").exists()


def test_redropping_the_same_file_is_a_no_op(session, inbox_dir, tmp_path):
    source = write_fitnotes_db(
        tmp_path / "b.fitnotes", [(TODAY.isoformat(), "Back Squat", 100.0, 5, 0)]
    )
    (inbox_dir / "b.fitnotes").write_bytes(source.read_bytes())
    assert inbox.scan(session)[0].written == 1

    (inbox_dir / "b.fitnotes").write_bytes(source.read_bytes())
    second = inbox.scan(session)[0]
    assert second.written == 0
    assert second.error is None


def test_unrecognised_files_are_set_aside_not_retried(session, inbox_dir):
    (inbox_dir / "notes.txt").write_text("not a backup")

    first = inbox.scan(session)
    assert first[0].error == "unrecognised file type"
    assert (inbox_dir / "rejected" / "notes.txt").exists()

    # Nothing left to report on the next pass.
    assert inbox.scan(session) == []


def test_one_bad_file_does_not_stop_the_others(session, inbox_dir):
    (inbox_dir / "a-junk.txt").write_text("nope")
    write_fitnotes_db(
        inbox_dir / "b-good.fitnotes", [(TODAY.isoformat(), "Back Squat", 100.0, 5, 0)]
    )
    results = {r.path.name: r for r in inbox.scan(session)}
    assert results["a-junk.txt"].error is not None
    assert results["b-good.fitnotes"].written == 1


def test_watched_folders_are_read_but_never_modified(session, inbox_dir, tmp_path):
    """FitNotes owns its backup folder; moving files out of it would be destructive."""
    watched = tmp_path / "FitNotes"
    watched.mkdir()
    backup = write_fitnotes_db(
        watched / "FitNotes_Backup.fitnotes", [(TODAY.isoformat(), "Back Squat", 100.0, 5, 0)]
    )

    results = inbox.scan(session, [watched])
    assert results[0].written == 1
    assert backup.exists(), "the backup must stay where its own app put it"
    assert not (watched / "processed").exists(), "no folders created in someone else's directory"


def test_unrelated_files_in_a_watched_folder_are_ignored_silently(session, inbox_dir, tmp_path):
    watched = tmp_path / "Documents"
    watched.mkdir()
    (watched / "shopping-list.txt").write_text("eggs")
    (watched / "photo.jpg").write_bytes(b"\xff\xd8\xff")

    assert inbox.scan(session, [watched]) == []
    assert (watched / "shopping-list.txt").exists()
    assert not (watched / "rejected").exists()


def test_a_watched_file_is_imported_once_until_its_contents_change(session, inbox_dir, tmp_path):
    watched = tmp_path / "FitNotes"
    watched.mkdir()
    path = watched / "FitNotes_Backup.fitnotes"
    write_fitnotes_db(path, [(TODAY.isoformat(), "Back Squat", 100.0, 5, 0)])

    assert inbox.scan(session, [watched])[0].written == 1
    assert inbox.scan(session, [watched]) == [], "unchanged file must not re-import"

    # An automatic backup overwrites the same name with new contents.
    path.unlink()
    write_fitnotes_db(
        path,
        [
            (TODAY.isoformat(), "Back Squat", 100.0, 5, 0),
            (TODAY.isoformat(), "Back Squat", 105.0, 5, 0),
        ],
    )
    assert inbox.scan(session, [watched])[0].written == 2


def test_a_watched_folder_that_does_not_exist_is_skipped(session, inbox_dir, tmp_path):
    assert inbox.scan(session, [tmp_path / "nope"]) == []


def test_the_inbox_is_not_scanned_twice_when_also_listed_as_watched(session, inbox_dir):
    write_fitnotes_db(
        inbox_dir / "b.fitnotes", [(TODAY.isoformat(), "Back Squat", 100.0, 5, 0)]
    )
    results = inbox.scan(session, [inbox_dir])
    assert len(results) == 1


def test_imported_watch_data_reaches_the_metrics_view(session, inbox_dir):
    write_gadgetbridge_db(inbox_dir / "w.db", [(epoch(TODAY, 9), 1234, 60, 1)])
    inbox.scan(session)
    session.flush()
    rows = rows_of(
        session,
        "SELECT value FROM v_daily_metrics_preferred WHERE date = :d AND metric = 'steps'",
        d=TODAY,
    )
    assert float(rows[0]["value"]) == 1234.0
