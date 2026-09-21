package dev.aura.core.imports

import dev.aura.core.Db
import java.math.BigDecimal
import java.time.LocalDate
import java.time.format.DateTimeParseException

/** One set as FitNotes recorded it, normalised to SI units. */
data class ParsedSet(
    val performedOn: LocalDate,
    val exercise: String,
    val category: String?,
    val weightKg: BigDecimal? = null,
    val reps: Int? = null,
    val distanceM: BigDecimal? = null,
    val durationS: Int? = null,
    val notes: String? = null,
)

data class ImportOutcome(val read: Int, val written: Int)

/**
 * Imports a FitNotes backup.
 *
 * The backup is itself a SQLite database, so it arrives here as a [Db] — which
 * is why opening the file is the caller's job: JDBC off-device, Android's own
 * SQLite on it.
 *
 * Re-running is safe. Each imported day is keyed on its date and its sets are
 * replaced wholesale, so a second import of an overlapping backup cannot
 * duplicate anything. Imported days land under `fitnotes_import`, separate from
 * anything logged in the app, so an import can never clobber a manual entry.
 */
object FitNotesImport {

    const val SOURCE = "fitnotes_import"

    fun parse(source: Db): List<ParsedSet> {
        val present = Parsing.tables(source)
        require(present.contains("training_log") && present.contains("exercise")) {
            "Not a FitNotes backup: expected training_log and exercise, found ${present.sorted()}"
        }

        val logColumns = Parsing.columns(source, "training_log")

        // FitNotes keeps a metric_weight column alongside the user's display
        // unit. Prefer it and take it as kilograms; only convert when the file
        // carries nothing but an imperial column.
        val metricWeight = Parsing.pick(logColumns, "metric_weight")
        val weightColumn = metricWeight ?: Parsing.pick(logColumns, "weight", "imperial_weight")
        val weightIsMetric = metricWeight != null

        val metricDistance = Parsing.pick(logColumns, "metric_distance")
        val distanceColumn = metricDistance ?: Parsing.pick(logColumns, "distance")
        val distanceIsMetric = metricDistance != null

        val unitColumn = Parsing.pick(logColumns, "unit")
        val durationColumn = Parsing.pick(logColumns, "duration_seconds")
        val commentColumn = Parsing.pick(logColumns, "comment", "notes")
        val repsColumn = Parsing.pick(logColumns, "reps")

        val categoryTable = Parsing.pick(present, "Category", "category")
        val categorySelect = if (categoryTable != null) "c.name" else "NULL"
        val categoryJoin =
            if (categoryTable != null) "LEFT JOIN \"$categoryTable\" c ON c._id = e.category_id"
            else ""

        fun column(name: String?, alias: String) =
            if (name != null) "t.\"$name\" AS $alias" else "NULL AS $alias"

        val selected =
            listOf(
                "t.date AS date",
                "e.name AS exercise",
                "$categorySelect AS category",
                column(weightColumn, "weight"),
                column(repsColumn, "reps"),
                column(distanceColumn, "distance"),
                column(durationColumn, "duration"),
                column(unitColumn, "unit"),
                column(commentColumn, "comment"),
            )

        return source.select(
            """
            SELECT ${selected.joinToString(", ")}
            FROM training_log t
            JOIN exercise e ON e._id = t.exercise_id
            $categoryJoin
            ORDER BY t.date
            """
        ) { row ->
            Row(
                date = row.stringOrNull("date"),
                exercise = row.stringOrNull("exercise"),
                category = row.stringOrNull("category"),
                weight = row.doubleOrNull("weight"),
                reps = row.longOrNull("reps"),
                distance = row.doubleOrNull("distance"),
                duration = row.longOrNull("duration"),
                unit = row.longOrNull("unit"),
                comment = row.stringOrNull("comment"),
            )
        }
            .mapNotNull { it.toParsedSet(weightIsMetric, distanceIsMetric) }
    }

    /** The raw shape of a training_log row, before units are resolved. */
    private data class Row(
        val date: String?,
        val exercise: String?,
        val category: String?,
        val weight: Double?,
        val reps: Long?,
        val distance: Double?,
        val duration: Long?,
        val unit: Long?,
        val comment: String?,
    )

    private fun Row.toParsedSet(weightIsMetric: Boolean, distanceIsMetric: Boolean): ParsedSet? {
        if (date.isNullOrBlank() || exercise.isNullOrBlank()) return null
        val performedOn =
            try {
                LocalDate.parse(date.take(10))
            } catch (_: DateTimeParseException) {
                return null
            }

        val imperial = unit == 1L

        var weightKg: BigDecimal? = null
        if (weight != null && weight > 0) {
            var value = BigDecimal(weight.toString())
            if (!weightIsMetric && imperial) value = value.multiply(LBS_TO_KG)
            weightKg = value.roundTo(3)
        }

        var distanceM: BigDecimal? = null
        if (distance != null && distance > 0) {
            val value = BigDecimal(distance.toString())
            // metric_distance is kilometres; a plain imperial distance is miles.
            val useMiles = imperial && !distanceIsMetric
            distanceM = (if (useMiles) value.multiply(MILES_TO_M) else value.multiply(KM_TO_M))
                .roundTo(2)
        }

        return ParsedSet(
            performedOn = performedOn,
            exercise = exercise.trim(),
            category = category?.trim()?.ifEmpty { null },
            weightKg = weightKg,
            reps = reps?.takeIf { it != 0L }?.toInt(),
            distanceM = distanceM,
            durationS = duration?.takeIf { it != 0L }?.toInt(),
            notes = comment?.ifEmpty { null },
        )
    }

    fun store(target: Db, parsed: List<ParsedSet>): ImportOutcome {
        if (parsed.isEmpty()) return ImportOutcome(read = 0, written = 0)

        val exerciseIds = resolveExercises(target, parsed)
        var written = 0

        parsed.groupBy { it.performedOn }.forEach { (day, entries) ->
            val externalId = day.toString()
            target.execute(
                """
                INSERT INTO workouts (performed_on, source, external_id) VALUES (?, ?, ?)
                ON CONFLICT (source, external_id) DO UPDATE SET performed_on = excluded.performed_on
                """,
                listOf(day.toString(), SOURCE, externalId),
            )
            val workoutId =
                target.selectOne(
                    "SELECT id FROM workouts WHERE source = ? AND external_id = ?",
                    listOf(SOURCE, externalId),
                ) { it.int("id") } ?: error("Workout for $day went missing after upsert")

            // Replace the day wholesale so a re-import cannot duplicate sets.
            target.execute("DELETE FROM sets WHERE workout_id = ?", listOf(workoutId))

            entries.forEachIndexed { index, entry ->
                target.execute(
                    """
                    INSERT INTO sets (workout_id, exercise_id, position, weight_kg, reps,
                                      distance_m, duration_s, notes, is_warmup)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    listOf(
                        workoutId,
                        exerciseIds.getValue(entry.exercise),
                        index + 1,
                        entry.weightKg?.toPlainString(),
                        entry.reps,
                        entry.distanceM?.toPlainString(),
                        entry.durationS,
                        entry.notes,
                    ),
                )
                written++
            }
        }
        return ImportOutcome(read = parsed.size, written = written)
    }

    fun run(source: Db, target: Db): ImportOutcome = store(target, parse(source))

    /** Resolve every exercise name to an id, creating the ones that are new. */
    private fun resolveExercises(target: Db, parsed: List<ParsedSet>): Map<String, Int> {
        val existing =
            target.select("SELECT id, name FROM exercises") {
                it.string("name").lowercase() to it.int("id")
            }.toMap().toMutableMap()

        val resolved = mutableMapOf<String, Int>()
        parsed.associate { it.exercise to it.category }.forEach { (name, category) ->
            val found =
                existing[name.lowercase()]
                    ?: run {
                        target.execute(
                            "INSERT INTO exercises (name, category, modality)" +
                                " VALUES (?, ?, 'weight_reps')",
                            listOf(name, category),
                        )
                        val id =
                            target.selectOne("SELECT last_insert_rowid() AS id") { it.int("id") }
                                ?: error("Could not create exercise $name")
                        existing[name.lowercase()] = id
                        id
                    }
            resolved[name] = found
        }
        return resolved
    }
}
