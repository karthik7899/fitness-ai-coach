-- A FitNotes backup that carries metric_weight, as recent versions do.
-- Weights here are already kilograms and must not be converted, even on the
-- rows whose unit flag says imperial — the metric column wins.
CREATE TABLE Category (_id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE exercise (_id INTEGER PRIMARY KEY, name TEXT, category_id INTEGER);
CREATE TABLE training_log (
    _id INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id INTEGER, date TEXT, metric_weight REAL, reps INTEGER,
    distance REAL, metric_distance REAL, duration_seconds INTEGER,
    unit INTEGER, comment TEXT);

INSERT INTO Category (_id, name) VALUES (1, 'Legs'), (2, 'Back'), (3, 'Cardio');
INSERT INTO exercise (_id, name, category_id) VALUES
    (1, 'Back Squat', 1), (2, 'Deadlift', 2), (3, 'Rower', 3);

INSERT INTO training_log (exercise_id, date, metric_weight, reps, unit, comment) VALUES
    (1, '2026-09-01', 100.0, 5, 0, NULL),
    (1, '2026-09-01', 102.5, 5, 0, 'felt heavy'),
    -- unit says imperial, but metric_weight is authoritative: stays 140kg.
    (2, '2026-09-01', 140.0, 3, 1, NULL),
    -- A bodyweight set: zero weight must not become 0kg, it must become null.
    (1, '2026-09-03', 0.0, 12, 0, NULL),
    -- Unparseable date: dropped rather than guessed at.
    (1, 'not-a-date', 90.0, 5, 0, NULL);

-- Distance in kilometres, plus a duration. 5km becomes 5000m.
INSERT INTO training_log (exercise_id, date, metric_distance, duration_seconds, unit) VALUES
    (3, '2026-09-03', 5.0, 1500, 0);
