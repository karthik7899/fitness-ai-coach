package dev.aura.core.presentation

import dev.aura.core.Backup
import dev.aura.core.DailyMetric
import dev.aura.core.DailyVolume
import dev.aura.core.Db
import dev.aura.core.ExerciseDay
import dev.aura.core.ExerciseTotal
import dev.aura.core.Metrics
import dev.aura.core.MuscleVolume
import dev.aura.core.Plan
import dev.aura.core.Settings
import dev.aura.core.Template
import dev.aura.core.TrainingLoad
import dev.aura.core.Workouts
import java.time.LocalDate

/** A labelled point for a chart. Charts take these, never database rows. */
data class Point(val date: LocalDate, val value: Double)

data class Series(val label: String, val points: List<Point>)

data class DashboardState(
    val wellness: List<DailyMetric>,
    val load: TrainingLoad?,
    val band: LoadBand,
    val recent: List<DailyVolume>,
    val templates: List<Template> = emptyList(),
    /** The template started today, if any, so its card can say "Continue". */
    val activeTemplate: String? = null,
)

data class TrendsState(
    val acute: Series,
    val chronic: Series,
    val band: LoadBand,
    val latest: TrainingLoad?,
    val byMuscle: List<MuscleVolume>,
    val exercises: List<ExerciseTotal>,
    val progression: List<ExerciseDay>,
    val progressionFor: String?,
)

data class LogState(
    val day: LocalDate,
    val sets: List<LoggedSet>,
    val recentExercises: List<String>,
    /** Today's plan from a starter workout, if one was started. */
    val plan: Plan? = null,
)

data class LoggedSet(
    val id: Int,
    val exercise: String,
    val weightKg: Double?,
    val reps: Int?,
    val isWarmup: Boolean,
)

data class SettingsState(
    val apiKeyHint: String?,
    val model: String,
    val watchFolders: List<String>,
    val database: Backup.Info,
)

/** How far back a screen is looking. */
enum class Range(val label: String, val days: Long) {
    MONTH("30 days", 30),
    QUARTER("90 days", 90),
    YEAR("1 year", 365),
}

/**
 * Everything the screens read, in one place.
 *
 * The UI calls these and renders what comes back; it does no querying and no
 * arithmetic of its own. That split is what lets the interesting half be tested
 * without a device — the Compose layer left holding only layout.
 */
class Store(private val db: Db) {

    private val metrics = Metrics(db)

    fun dashboard(today: LocalDate = LocalDate.now()): DashboardState {
        val summary = metrics.summary()
        return DashboardState(
            wellness = summary.latestMetrics.values.sortedBy { Format.metricName(it.metric) },
            load = summary.load,
            band = LoadBand.of(summary.load?.acwr),
            recent = summary.recentWorkouts,
            templates = Workouts.templates,
            activeTemplate = Workouts.plan(db, today)?.template?.id,
        )
    }

    /** Make a starter workout today's plan; the Log screen then follows it. */
    fun startWorkout(id: String, today: LocalDate = LocalDate.now()) {
        requireNotNull(Workouts.start(db, id, today)) { "No workout named $id." }
    }

    fun finishWorkout() = Workouts.finish(db)

    fun trends(
        range: Range = Range.QUARTER,
        exercise: String? = null,
        today: LocalDate = LocalDate.now(),
    ): TrendsState {
        val start = today.minusDays(range.days)
        val load = metrics.trainingLoad(start, today)
        val exercises = metrics.exercisesWithHistory()
        val chosen = exercise ?: exercises.firstOrNull()?.exercise

        return TrendsState(
            acute = Series("Acute (7-day)", load.map { Point(it.date, it.acute7d) }),
            chronic = Series("Chronic (28-day)", load.map { Point(it.date, it.chronic28d) }),
            band = LoadBand.of(load.lastOrNull()?.acwr),
            latest = load.lastOrNull(),
            byMuscle = metrics.volumeByMuscle(start, today),
            exercises = exercises,
            progression =
                chosen?.let { metrics.exerciseProgression(it, start, today) }.orEmpty(),
            progressionFor = chosen,
        )
    }

    fun log(day: LocalDate = LocalDate.now()): LogState =
        LogState(
            day = day,
            sets =
                db.select(
                    """
                    SELECT s.id, e.name AS exercise, s.weight_kg, s.reps, s.is_warmup
                    FROM sets s
                    JOIN workouts w ON w.id = s.workout_id
                    JOIN exercises e ON e.id = s.exercise_id
                    WHERE w.performed_on = ?
                    ORDER BY s.position
                    """,
                    listOf(day.toString()),
                ) {
                    LoggedSet(
                        id = it.int("id"),
                        exercise = it.string("exercise"),
                        weightKg = it.doubleOrNull("weight_kg"),
                        reps = it.longOrNull("reps")?.toInt(),
                        isWarmup = it.boolean("is_warmup"),
                    )
                },
            // What you trained recently is what you are most likely logging now.
            recentExercises =
                db.select(
                    """
                    SELECT e.name AS name, MAX(w.performed_on) AS last_done
                    FROM sets s
                    JOIN workouts w ON w.id = s.workout_id
                    JOIN exercises e ON e.id = s.exercise_id
                    GROUP BY e.name
                    ORDER BY last_done DESC
                    LIMIT 20
                    """
                ) { it.string("name") },
            plan = Workouts.plan(db, day),
        )

    fun settings(): SettingsState =
        SettingsState(
            apiKeyHint = Settings.maskedApiKey(db),
            model = Settings.model(db),
            watchFolders = Settings.watchFolders(db),
            database = Backup.describe(db),
        )

    /** Add a set to today's manually logged workout, creating what is missing. */
    fun addSet(
        exercise: String,
        weightKg: Double?,
        reps: Int?,
        isWarmup: Boolean = false,
        day: LocalDate = LocalDate.now(),
    ) {
        val name = exercise.trim()
        require(name.isNotEmpty()) { "An exercise needs a name." }

        val exerciseId =
            db.selectOne(
                "SELECT id FROM exercises WHERE lower(name) = lower(?)",
                listOf(name),
            ) { it.int("id") }
                ?: run {
                    db.execute(
                        "INSERT INTO exercises (name, modality) VALUES (?, 'weight_reps')",
                        listOf(name),
                    )
                    lastId()
                }

        val workoutId =
            db.selectOne(
                "SELECT id FROM workouts WHERE performed_on = ? AND source = 'manual'",
                listOf(day.toString()),
            ) { it.int("id") }
                ?: run {
                    db.execute(
                        "INSERT INTO workouts (performed_on, source) VALUES (?, 'manual')",
                        listOf(day.toString()),
                    )
                    lastId()
                }

        val position =
            (db.selectOne(
                "SELECT COALESCE(MAX(position), 0) AS p FROM sets WHERE workout_id = ?",
                listOf(workoutId.toString()),
            ) { it.int("p") } ?: 0) + 1

        db.execute(
            """
            INSERT INTO sets (workout_id, exercise_id, position, weight_kg, reps, is_warmup)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            listOf(workoutId, exerciseId, position, weightKg, reps, if (isWarmup) 1 else 0),
        )
    }

    fun deleteSet(id: Int) {
        db.execute("DELETE FROM sets WHERE id = ?", listOf(id))
    }

    private fun lastId(): Int =
        db.selectOne("SELECT last_insert_rowid() AS id") { it.int("id") }
            ?: error("No row inserted")
}
