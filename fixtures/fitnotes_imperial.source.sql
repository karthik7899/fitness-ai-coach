-- An older FitNotes backup with no metric_weight column at all. Here the unit
-- flag is the only thing that says what the numbers mean, so 1 means pounds
-- and the weights must be converted.
CREATE TABLE exercise (_id INTEGER PRIMARY KEY, name TEXT, category_id INTEGER);
CREATE TABLE training_log (
    _id INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id INTEGER, date TEXT, weight REAL, reps INTEGER,
    distance REAL, unit INTEGER);

INSERT INTO exercise (_id, name, category_id) VALUES (1, 'Bench Press', NULL), (2, 'Run', NULL);

INSERT INTO training_log (exercise_id, date, weight, reps, unit) VALUES
    (1, '2026-09-05', 225.0, 5, 1),   -- 225 lb
    (1, '2026-09-05', 100.0, 5, 0);   -- already kg: unit 0 means metric

-- Miles, because the unit flag says imperial and there is no metric_distance.
INSERT INTO training_log (exercise_id, date, distance, unit) VALUES
    (2, '2026-09-06', 3.1, 1);
