package dev.aura.core

import java.time.LocalDate

val TODAY: LocalDate = LocalDate.now()

/** A set as the fixtures describe one: weight, reps, and whether it is a warmup. */
data class SetSpec(val exercise: String, val weightKg: Double?, val reps: Int?, val warmup: Boolean = false)

/**
 * The same three exercises the Python fixtures use, including the deliberately
 * unmapped one that exercises the category fallback.
 */
fun Db.seedExercises() {
    fun exercise(id: Int, name: String, category: String, muscles: List<String>) {
        execute(
            "INSERT INTO exercises (id, name, category, modality) VALUES (?, ?, ?, 'weight_reps')",
            listOf(id, name, category),
        )
        muscles.forEach {
            execute(
                "INSERT INTO exercise_muscles (exercise_id, muscle, is_primary) VALUES (?, ?, 1)",
                listOf(id, it),
            )
        }
    }
    exercise(1, "Back Squat", "Legs", listOf("quads", "glutes"))
    exercise(2, "Bench Press", "Chest", listOf("chest", "triceps"))
    exercise(3, "Sled Push", "Conditioning", emptyList())
}

/**
 * Ids are left to SQLite rather than assigned here, which also keeps the
 * autoincrement behaviour under test: a BIGINT primary key silently gets none.
 */
fun Db.addWorkout(day: LocalDate, sets: List<SetSpec>): Int {
    execute(
        "INSERT INTO workouts (performed_on, source) VALUES (?, 'manual')",
        listOf(day.toString()),
    )
    val workoutId = lastInsertRowId()
    sets.forEachIndexed { index, spec ->
        val exerciseId =
            selectOne("SELECT id FROM exercises WHERE name = ?", listOf(spec.exercise)) {
                it.int("id")
            } ?: error("No such exercise: ${spec.exercise}")
        execute(
            """
            INSERT INTO sets (workout_id, exercise_id, position, weight_kg, reps, is_warmup)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            listOf(workoutId, exerciseId, index + 1, spec.weightKg, spec.reps, spec.warmup),
        )
    }
    return workoutId
}

fun Db.lastInsertRowId(): Int =
    selectOne("SELECT last_insert_rowid() AS id") { it.int("id") } ?: error("No row inserted")

fun Db.addDailyMetric(day: LocalDate, metric: String, source: String, value: Double, unit: String) {
    execute(
        "INSERT INTO daily_metrics (date, metric, source, value, unit) VALUES (?, ?, ?, ?, ?)",
        listOf(day.toString(), metric, source, value, unit),
    )
}
