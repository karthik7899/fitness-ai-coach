-- The canonical rows a FitNotes import must produce.
--
-- Every value is rendered to text by SQLite itself rather than by the calling
-- language, so Python and Kotlin compare byte-identical strings and any
-- difference is a real difference in the data.
SELECT w.performed_on
       || ',' || e.name
       || ',' || s.position
       || ',' || COALESCE(CAST(s.weight_kg AS TEXT), '')
       || ',' || COALESCE(CAST(s.reps AS TEXT), '')
       || ',' || COALESCE(CAST(s.distance_m AS TEXT), '')
       || ',' || COALESCE(CAST(s.duration_s AS TEXT), '')
       || ',' || COALESCE(s.notes, '')
       AS line
FROM sets s
JOIN workouts w ON w.id = s.workout_id
JOIN exercises e ON e.id = s.exercise_id
WHERE w.source = 'fitnotes_import'
ORDER BY w.performed_on, s.position
