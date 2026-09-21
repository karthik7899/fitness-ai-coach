package dev.aura.core.agent

import dev.aura.core.Db
import dev.aura.core.Row
import java.time.LocalDate
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.Json

/**
 * The coach's tool surface.
 *
 * Every number the coach quotes comes from one of these, which read the SQL
 * views. The model is never asked to aggregate or compute — only to interpret.
 *
 * The declarations are not written here: `tools.json` is generated from the
 * Python app by `scripts/export_tools.py`, so the two coaches cannot end up
 * able to answer different questions, or describing the same tool differently
 * to the model. Only the handlers are Kotlin.
 */
object Tools {

    const val RESOURCE_PATH: String = "/aura/tools.json"
    const val MAX_ROWS: Int = 400

    private val json = Json { ignoreUnknownKeys = true; prettyPrint = false }

    /** The generated declarations, as the model is given them. */
    fun declarations(): List<JsonObject> {
        val text =
            Tools::class.java.getResourceAsStream(RESOURCE_PATH)
                ?.bufferedReader()
                ?.use { it.readText() }
                ?: error(
                    "$RESOURCE_PATH is missing from the classpath. " +
                        "Run scripts/export_tools.py to generate it."
                )
        return json.parseToJsonElement(text).jsonObject["tools"]!!.jsonArray.map { it.jsonObject }
    }

    fun names(): List<String> = declarations().map { it["name"]!!.jsonPrimitive.content }

    /**
     * Run a declared tool.
     *
     * An unknown name is an error object rather than an exception: the model
     * chose it, and telling it what went wrong is more useful than a crash.
     */
    fun call(db: Db, name: String, arguments: JsonObject): JsonObject =
        when (name) {
            "get_daily_metrics" -> getDailyMetrics(db, arguments)
            "get_training_load" -> getTrainingLoad(db, arguments)
            "get_exercise_history" -> getExerciseHistory(db, arguments)
            "get_volume_summary" -> getVolumeSummary(db, arguments)
            "get_recent_activities" -> getRecentActivities(db, arguments)
            "get_workout" -> getWorkout(db, arguments)
            "list_exercises" -> listExercises(db, arguments)
            "log_set" -> logSet(db, arguments)
            "remember" -> remember(db, arguments)
            else -> error("Unknown tool: $name")
        }

    // ----------------------------------------------------------------------
    // Handlers
    // ----------------------------------------------------------------------

    private fun getDailyMetrics(db: Db, args: JsonObject): JsonObject {
        val metrics = args.stringList("metrics")
        // Not `metric = ANY(:array)`: arrays are a PostgreSQL type, and this
        // query has to run on SQLite. The Python side builds the clause too.
        val filter =
            if (metrics.isEmpty()) "" else "AND metric IN (${metrics.joinToString(",") { "?" }})"
        val rows =
            db.rows(
                """
                SELECT date, metric, value, unit, source
                FROM v_daily_metrics_preferred
                WHERE date BETWEEN ? AND ?
                $filter
                ORDER BY date DESC, metric
                LIMIT $MAX_ROWS
                """,
                listOf(args.required("start_date"), args.required("end_date")) + metrics,
            )
        return buildJsonObject {
            put("rows", rows)
            put("count", JsonPrimitive(rows.size))
        }
    }

    private fun getTrainingLoad(db: Db, args: JsonObject): JsonObject {
        val rows =
            db.rows(
                """
                SELECT date, strength_tonnes, cardio_minutes, cardio_km,
                       load_au, acute_7d, chronic_28d, acwr
                FROM v_training_load
                WHERE date BETWEEN ? AND ?
                ORDER BY date DESC
                LIMIT $MAX_ROWS
                """,
                listOf(args.required("start_date"), args.required("end_date")),
            )
        return buildJsonObject {
            put("rows", rows)
            put("count", JsonPrimitive(rows.size))
            put(
                "note",
                JsonPrimitive(
                    "load_au = strength tonnes + cardio minutes / 10. ACWR is the 7-day mean " +
                        "over the 28-day mean; roughly 0.8-1.3 is a steady build, above ~1.5 " +
                        "is a sharp spike in load relative to recent history."
                ),
            )
        }
    }

    private fun getExerciseHistory(db: Db, args: JsonObject): JsonObject {
        val wanted = args.required("exercise").trim()
        val match =
            db.selectOne(
                "SELECT id, name FROM exercises WHERE lower(name) = lower(?)",
                listOf(wanted),
            ) { it.int("id") to it.string("name") }

        if (match == null) {
            val near =
                db.select(
                    "SELECT name FROM exercises WHERE lower(name) LIKE lower(?) LIMIT 10",
                    listOf("%$wanted%"),
                ) { it.string("name") }
            return buildJsonObject {
                put("error", JsonPrimitive("No exercise named '$wanted'."))
                put("did_you_mean", JsonArray(near.map { JsonPrimitive(it) }))
            }
        }

        val limit = (args.intOrNull("limit") ?: 30).coerceAtMost(MAX_ROWS)
        val rows =
            db.rows(
                """
                SELECT date, best_e1rm_kg, top_weight_kg, volume_kg, working_sets
                FROM v_exercise_e1rm_daily
                WHERE exercise_id = ?
                ORDER BY date DESC
                LIMIT $limit
                """,
                listOf(match.first.toString()),
            )
        return buildJsonObject {
            put("exercise", JsonPrimitive(match.second))
            put("sessions", rows)
            put("count", JsonPrimitive(rows.size))
        }
    }

    private fun getVolumeSummary(db: Db, args: JsonObject): JsonObject {
        val groupBy = args.stringOrNull("group_by") ?: "muscle"
        val sql =
            when (groupBy) {
                "muscle" ->
                    """
                    SELECT muscle, SUM(volume_kg) AS volume_kg, SUM(working_sets) AS working_sets
                    FROM v_weekly_muscle_volume
                    WHERE week_start BETWEEN ? AND ?
                    GROUP BY muscle ORDER BY volume_kg DESC
                    """
                "week" ->
                    """
                    SELECT week_start, SUM(volume_kg) AS volume_kg,
                           SUM(working_sets) AS working_sets
                    FROM v_weekly_muscle_volume
                    WHERE week_start BETWEEN ? AND ?
                    GROUP BY week_start ORDER BY week_start DESC
                    """
                "exercise" ->
                    """
                    SELECT exercise, SUM(volume_kg) AS volume_kg,
                           SUM(working_sets) AS working_sets, MAX(best_e1rm_kg) AS best_e1rm_kg
                    FROM v_exercise_e1rm_daily
                    WHERE date BETWEEN ? AND ?
                    GROUP BY exercise ORDER BY volume_kg DESC
                    """
                "day" ->
                    """
                    SELECT date, volume_kg, working_sets, exercises
                    FROM v_daily_volume
                    WHERE date BETWEEN ? AND ?
                    ORDER BY date DESC
                    """
                else ->
                    return buildJsonObject {
                        put("error", JsonPrimitive("Unknown group_by '$groupBy'."))
                    }
            }
        val rows = db.rows(sql, listOf(args.required("start_date"), args.required("end_date")))
        return buildJsonObject {
            put("group_by", JsonPrimitive(groupBy))
            put("rows", JsonArray(rows.take(MAX_ROWS)))
            put("count", JsonPrimitive(rows.size))
        }
    }

    private fun getRecentActivities(db: Db, args: JsonObject): JsonObject {
        // Built rather than written with `(? IS NULL OR col = ?)`, which
        // PostgreSQL cannot type-infer and SQLite would take differently.
        val filters = mutableListOf<String>()
        val params = mutableListOf<String>()
        args.stringOrNull("sport_type")?.let {
            filters += "AND sport_type = ?"
            params += it
        }
        args.stringOrNull("since")?.let {
            filters += "AND started_at >= ?"
            params += it
        }
        val limit = (args.intOrNull("limit") ?: 20).coerceAtMost(MAX_ROWS)

        val rows =
            db.rows(
                """
                SELECT external_id, sport_type, name, started_at, distance_m, moving_time_s,
                       elevation_gain_m, average_hr, max_hr, calories,
                       CASE WHEN distance_m > 0 AND moving_time_s > 0
                            THEN ROUND(((moving_time_s / 60.0) / (distance_m / 1000.0)) * 100)
                                 / 100.0
                       END AS pace_min_per_km
                FROM activities
                WHERE 1 = 1
                ${filters.joinToString(" ")}
                ORDER BY started_at DESC
                LIMIT $limit
                """,
                params,
            )
        return buildJsonObject {
            put("rows", rows)
            put("count", JsonPrimitive(rows.size))
        }
    }

    private fun getWorkout(db: Db, args: JsonObject): JsonObject {
        val day = args.required("performed_on")
        val rows =
            db.rows(
                """
                SELECT exercise, category, reps, weight_kg, rpe, is_warmup, volume_kg, e1rm_kg
                FROM v_sets_enriched
                WHERE performed_on = ?
                ORDER BY exercise, id
                """,
                listOf(day),
            )
        val notes =
            db.selectOne("SELECT notes FROM workouts WHERE performed_on = ?", listOf(day)) {
                it.stringOrNull("notes")
            }
        return buildJsonObject {
            put("date", JsonPrimitive(day))
            put("sets", rows)
            put("count", JsonPrimitive(rows.size))
            put("notes", notes?.let { JsonPrimitive(it) } ?: JsonNull)
        }
    }

    private fun listExercises(db: Db, args: JsonObject): JsonObject {
        val search = args.stringOrNull("search")?.trim()
        val filter = if (search.isNullOrEmpty()) "" else "AND lower(name) LIKE lower(?)"
        val rows =
            db.rows(
                """
                SELECT name, category, modality
                FROM exercises
                WHERE NOT is_archived
                $filter
                ORDER BY name
                LIMIT $MAX_ROWS
                """,
                if (search.isNullOrEmpty()) emptyList() else listOf("%$search%"),
            )
        return buildJsonObject { put("exercises", rows) }
    }

    private fun logSet(db: Db, args: JsonObject): JsonObject {
        val day = args.stringOrNull("performed_on") ?: LocalDate.now().toString()
        val name = args.required("exercise").trim()

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
                    db.lastInsertId()
                }

        val workoutId =
            db.selectOne(
                "SELECT id FROM workouts WHERE performed_on = ? AND source = 'manual'",
                listOf(day),
            ) { it.int("id") }
                ?: run {
                    db.execute(
                        "INSERT INTO workouts (performed_on, source) VALUES (?, 'manual')",
                        listOf(day),
                    )
                    db.lastInsertId()
                }

        val position =
            (db.selectOne(
                "SELECT COALESCE(MAX(position), 0) AS p FROM sets WHERE workout_id = ?",
                listOf(workoutId.toString()),
            ) { it.int("p") } ?: 0) + 1

        val reps = args.intOrNull("reps")
        val weight = args.doubleOrNull("weight_kg")
        db.execute(
            """
            INSERT INTO sets (workout_id, exercise_id, position, reps, weight_kg, rpe, is_warmup)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            listOf(
                workoutId,
                exerciseId,
                position,
                reps,
                weight,
                args.doubleOrNull("rpe"),
                if (args.booleanOrNull("is_warmup") == true) 1 else 0,
            ),
        )

        return buildJsonObject {
            put("logged", JsonPrimitive(true))
            put("set_id", JsonPrimitive(db.lastInsertId()))
            put("exercise", JsonPrimitive(name))
            put("date", JsonPrimitive(day))
            put("reps", reps?.let { JsonPrimitive(it) } ?: JsonNull)
            put("weight_kg", weight?.let { JsonPrimitive(it) } ?: JsonNull)
            put("position", JsonPrimitive(position))
        }
    }

    private fun remember(db: Db, args: JsonObject): JsonObject {
        val kind = args.required("kind")
        val content = args.required("content").trim()
        db.execute(
            "INSERT INTO coach_notes (kind, content, is_active) VALUES (?, ?, 1)",
            listOf(kind, content),
        )
        return buildJsonObject {
            put("saved", JsonPrimitive(true))
            put("id", JsonPrimitive(db.lastInsertId()))
            put("kind", JsonPrimitive(kind))
            put("content", JsonPrimitive(content))
        }
    }
}

// --------------------------------------------------------------------------
// Small helpers
// --------------------------------------------------------------------------

internal fun Db.lastInsertId(): Int =
    selectOne("SELECT last_insert_rowid() AS id") { it.int("id") } ?: error("No row inserted")

/** A result set as a JSON array of objects, typed the way SQLite typed it. */
internal fun Db.rows(sql: String, args: List<Any?> = emptyList()): JsonArray =
    JsonArray(select(sql, args) { it.toJson() })

internal fun Row.toJson(): JsonObject = buildJsonObject {
    for (column in columns()) {
        put(column, value(column).toJsonElement())
    }
}

private fun Any?.toJsonElement(): JsonElement =
    when (this) {
        null -> JsonNull
        is String -> JsonPrimitive(this)
        is Long -> JsonPrimitive(this)
        is Double -> JsonPrimitive(this)
        is Number -> JsonPrimitive(this)
        is Boolean -> JsonPrimitive(this)
        else -> JsonPrimitive(toString())
    }

private fun JsonObject.required(key: String): String =
    this[key]?.jsonPrimitive?.content ?: error("Tool call is missing '$key'.")

private fun JsonObject.stringOrNull(key: String): String? =
    (this[key] as? JsonPrimitive)?.takeIf { it != JsonNull }?.content

private fun JsonObject.intOrNull(key: String): Int? = stringOrNull(key)?.toIntOrNull()

private fun JsonObject.doubleOrNull(key: String): Double? = stringOrNull(key)?.toDoubleOrNull()

private fun JsonObject.booleanOrNull(key: String): Boolean? =
    stringOrNull(key)?.lowercase()?.let { it == "true" || it == "1" }

private fun JsonObject.stringList(key: String): List<String> =
    (this[key] as? JsonArray)?.map { it.jsonPrimitive.content } ?: emptyList()
