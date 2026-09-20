package dev.aura.core

import java.time.LocalDate

/** A resolved wellness reading: one value per metric per day, source already chosen. */
data class DailyMetric(
    val date: LocalDate,
    val metric: String,
    val value: Double,
    val unit: String?,
    val source: String,
)

/** A day on the training-load spine. Rest days are present, with a real zero. */
data class TrainingLoad(
    val date: LocalDate,
    val strengthTonnes: Double,
    val cardioMinutes: Double,
    val cardioKm: Double,
    val loadAu: Double,
    val acute7d: Double,
    val chronic28d: Double,
    /** Null until there is enough history for the ratio to mean anything. */
    val acwr: Double?,
)

data class MuscleVolume(val muscle: String, val volumeKg: Double, val workingSets: Int)

data class DailyVolume(
    val date: LocalDate,
    val volumeKg: Double,
    val workingSets: Int,
    val exercises: Int,
)

data class ExerciseTotal(val exercise: String, val volumeKg: Double, val sessions: Int)

data class ExerciseDay(
    val date: LocalDate,
    /** Null when no set that day was in the 1–12 rep range the estimate is guarded to. */
    val bestE1rmKg: Double?,
    val topWeightKg: Double?,
    val volumeKg: Double,
    val workingSets: Int,
)

data class Summary(
    val latestMetrics: Map<String, DailyMetric>,
    val load: TrainingLoad?,
    val recentWorkouts: List<DailyVolume>,
)

/**
 * Every number the app displays, read from the SQL views.
 *
 * The queries are the same ones the Python API serves, against the same views,
 * so a figure on the phone and the same figure in the browser come from one
 * definition. Nothing here computes a training metric in Kotlin — arithmetic in
 * two languages is arithmetic that will eventually disagree.
 */
class Metrics(private val db: Db) {

    fun dailyMetrics(start: LocalDate, end: LocalDate): List<DailyMetric> =
        db.select(
            """
            SELECT date, metric, value, unit, source
            FROM v_daily_metrics_preferred
            WHERE date BETWEEN ? AND ?
            ORDER BY date DESC, metric
            """,
            listOf(start.toString(), end.toString()),
        ) { it.toDailyMetric() }

    fun trainingLoad(start: LocalDate, end: LocalDate): List<TrainingLoad> =
        db.select(
            """
            SELECT date, strength_tonnes, cardio_minutes, cardio_km, load_au,
                   acute_7d, chronic_28d, acwr
            FROM v_training_load
            WHERE date BETWEEN ? AND ?
            ORDER BY date
            """,
            listOf(start.toString(), end.toString()),
        ) { it.toTrainingLoad() }

    fun volumeByMuscle(start: LocalDate, end: LocalDate): List<MuscleVolume> =
        db.select(
            """
            SELECT muscle, SUM(volume_kg) AS volume_kg, SUM(working_sets) AS working_sets
            FROM v_weekly_muscle_volume
            WHERE week_start BETWEEN ? AND ?
            GROUP BY muscle
            ORDER BY volume_kg DESC
            """,
            listOf(start.toString(), end.toString()),
        ) { MuscleVolume(it.string("muscle"), it.double("volume_kg"), it.int("working_sets")) }

    fun volumeByDay(start: LocalDate, end: LocalDate): List<DailyVolume> =
        db.select(
            """
            SELECT date, volume_kg, working_sets, exercises
            FROM v_daily_volume
            WHERE date BETWEEN ? AND ?
            ORDER BY date
            """,
            listOf(start.toString(), end.toString()),
        ) { it.toDailyVolume() }

    /** Exercises that actually have logged sets, heaviest-trained first. */
    fun exercisesWithHistory(): List<ExerciseTotal> =
        db.select(
            """
            SELECT exercise, SUM(volume_kg) AS volume_kg, COUNT(DISTINCT date) AS sessions
            FROM v_exercise_e1rm_daily
            GROUP BY exercise
            ORDER BY volume_kg DESC
            """
        ) { ExerciseTotal(it.string("exercise"), it.double("volume_kg"), it.int("sessions")) }

    fun exerciseProgression(name: String, start: LocalDate, end: LocalDate): List<ExerciseDay> =
        db.select(
            """
            SELECT date, best_e1rm_kg, top_weight_kg, volume_kg, working_sets
            FROM v_exercise_e1rm_daily
            WHERE lower(exercise) = lower(?)
              AND date BETWEEN ? AND ?
            ORDER BY date
            """,
            listOf(name, start.toString(), end.toString()),
        ) {
            ExerciseDay(
                date = LocalDate.parse(it.string("date")),
                bestE1rmKg = it.doubleOrNull("best_e1rm_kg"),
                topWeightKg = it.doubleOrNull("top_weight_kg"),
                volumeKg = it.double("volume_kg"),
                workingSets = it.int("working_sets"),
            )
        }

    /** Everything the dashboard header needs, in one place. */
    fun summary(): Summary {
        val latest =
            db.select(
                """
                SELECT date, metric, value, unit, source
                FROM v_daily_metrics_preferred
                WHERE (metric, date) IN (
                    SELECT metric, MAX(date) FROM v_daily_metrics_preferred GROUP BY metric
                )
                """
            ) { it.toDailyMetric() }

        val load =
            db.selectOne(
                """
                SELECT date, strength_tonnes, cardio_minutes, cardio_km, load_au,
                       acute_7d, chronic_28d, acwr
                FROM v_training_load
                WHERE date = CURRENT_DATE
                """
            ) { it.toTrainingLoad() }

        val recent =
            db.select(
                """
                SELECT date, volume_kg, working_sets, exercises
                FROM v_daily_volume
                ORDER BY date DESC
                LIMIT 7
                """
            ) { it.toDailyVolume() }

        return Summary(latest.associateBy { it.metric }, load, recent)
    }
}

private fun Row.toDailyMetric() =
    DailyMetric(
        date = LocalDate.parse(string("date")),
        metric = string("metric"),
        value = double("value"),
        unit = stringOrNull("unit"),
        source = string("source"),
    )

private fun Row.toDailyVolume() =
    DailyVolume(
        date = LocalDate.parse(string("date")),
        volumeKg = double("volume_kg"),
        workingSets = int("working_sets"),
        exercises = int("exercises"),
    )

private fun Row.toTrainingLoad() =
    TrainingLoad(
        date = LocalDate.parse(string("date")),
        strengthTonnes = double("strength_tonnes"),
        cardioMinutes = double("cardio_minutes"),
        cardioKm = double("cardio_km"),
        loadAu = double("load_au"),
        acute7d = double("acute_7d"),
        chronic28d = double("chronic_28d"),
        acwr = doubleOrNull("acwr"),
    )
