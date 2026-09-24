package dev.aura.core

import java.time.LocalDate
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

/** One exercise in a template, with its target. */
@Serializable
data class Planned(val exercise: String, val sets: Int, val reps: Int)

/** A starter workout: a named list of exercises with targets. */
@Serializable
data class Template(
    val id: String,
    val name: String,
    val about: String,
    val exercises: List<Planned>,
)

@Serializable
data class CatalogueEntry(
    val name: String,
    val category: String,
    val modality: String,
    val muscles: List<String>,
    val aliases: List<String> = emptyList(),
)

/** Where one exercise of today's plan stands. */
data class PlanEntry(
    /** The exercise as it exists here, which may be an alias of [planned]. */
    val exercise: String,
    /** The template's name for it. */
    val planned: String,
    val sets: Int,
    val reps: Int,
    /** Working sets of it logged today, from any source. */
    val done: Int,
    /** The most recent working weight, today's included. */
    val lastWeightKg: Double?,
) {
    val complete: Boolean
        get() = done >= sets
}

data class Plan(val template: Template, val day: LocalDate, val entries: List<PlanEntry>) {
    val complete: Boolean
        get() = entries.all { it.complete }
}

/**
 * Starter workouts, and the plan started from one.
 *
 * The templates are generated from the Python app by
 * scripts/export_workouts.py, like the schema, so both apps offer the same
 * sessions and create their exercises with the same muscles. Starting one
 * logs nothing: it makes sure the exercises exist and marks the template as
 * today's plan, under the same settings key the desktop app uses.
 *
 * Exercises are matched by name and by alias, so a template's "Bench Press"
 * is the "Flat Barbell Bench Press" an imported history already has.
 */
object Workouts {

    const val RESOURCE_PATH: String = "/aura/workouts.json"
    const val ACTIVE: String = "workout"

    @Serializable
    private data class Document(
        val catalogue: List<CatalogueEntry>,
        val templates: List<Template>,
    )

    private val document: Document by lazy {
        val text =
            Workouts::class.java.getResourceAsStream(RESOURCE_PATH)
                ?.bufferedReader()
                ?.use { it.readText() }
                ?: error(
                    "$RESOURCE_PATH is missing from the classpath. " +
                        "Run scripts/export_workouts.py to generate it."
                )
        Json { ignoreUnknownKeys = true }.decodeFromString(Document.serializer(), text)
    }

    val templates: List<Template>
        get() = document.templates

    fun template(id: String): Template? = templates.firstOrNull { it.id == id }

    private val notAlphanumeric = Regex("[^a-z0-9]+")

    /** "Pull-Up", "pull up" and "Pullup" compare equal, as in workouts.normalise. */
    fun normalise(name: String): String = notAlphanumeric.replace(name.lowercase(), "")

    /** The template's name for an exercise, then its aliases, in preference order. */
    fun namesFor(exercise: String): List<String> {
        val entry = document.catalogue.firstOrNull { it.name.equals(exercise, ignoreCase = true) }
        return listOf(exercise) + entry?.aliases.orEmpty()
    }

    private data class Match(val id: Int, val name: String, val sets: Int, val rank: Int)

    /**
     * The existing exercise a template's exercise means, as (id, name).
     *
     * Any exercise under its name or an alias counts. When several do, the one
     * with the most working sets wins, since that is where the history is; a
     * tie goes to the earlier name in the alias list, then to the older row.
     * The same rule as workouts.resolve, which WorkoutsTest pins.
     */
    fun resolve(db: Db, exercise: String): Pair<Int, String>? {
        val rank = HashMap<String, Int>()
        namesFor(exercise).forEachIndexed { i, name -> rank.putIfAbsent(normalise(name), i) }
        val best =
            db.select(
                """
                SELECT e.id, e.name, COUNT(s.id) AS sets
                FROM exercises e
                LEFT JOIN sets s ON s.exercise_id = e.id AND s.is_warmup = 0
                GROUP BY e.id, e.name
                """
            ) { Match(it.int("id"), it.string("name"), it.int("sets"), -1) }
                .mapNotNull { m -> rank[normalise(m.name)]?.let { m.copy(rank = it) } }
                .maxWithOrNull(
                    compareBy<Match> { it.sets }.thenByDescending { it.rank }.thenByDescending { it.id }
                )
        return best?.let { it.id to it.name }
    }

    /**
     * Create the template's missing exercises and make it today's plan.
     *
     * An exercise that already exists is left exactly as it is, even with
     * different muscles: it may have come from an import, and its history
     * hangs off it.
     */
    fun start(db: Db, id: String, day: LocalDate): Plan? {
        val chosen = template(id) ?: return null
        val catalogue = document.catalogue.associateBy { it.name.lowercase() }
        for (planned in chosen.exercises) {
            if (resolve(db, planned.exercise) != null) continue
            val entry = catalogue.getValue(planned.exercise.lowercase())
            db.execute(
                "INSERT INTO exercises (name, category, modality) VALUES (?, ?, ?)",
                listOf(entry.name, entry.category, entry.modality),
            )
            val newId =
                exerciseId(db, entry.name) ?: error("${entry.name} was not created")
            for (muscle in entry.muscles) {
                db.execute(
                    "INSERT INTO exercise_muscles (exercise_id, muscle, is_primary) VALUES (?, ?, 1)",
                    listOf(newId, muscle),
                )
            }
        }
        Settings.write(
            db,
            ACTIVE,
            buildJsonObject {
                put("template", id)
                put("day", day.toString())
            },
        )
        return plan(db, day)
    }

    fun finish(db: Db) = Settings.clear(db, ACTIVE)

    /** Today's plan with progress through it, or null if none was started today. */
    fun plan(db: Db, day: LocalDate): Plan? {
        val active = Settings.read(db, ACTIVE) ?: return null
        if (active["day"]?.jsonPrimitive?.content != day.toString()) return null
        val chosen = template(active["template"]?.jsonPrimitive?.content.orEmpty()) ?: return null

        val entries =
            chosen.exercises.map { planned ->
                val found = resolve(db, planned.exercise)
                val id = found?.first
                PlanEntry(
                    exercise = found?.second ?: planned.exercise,
                    planned = planned.exercise,
                    sets = planned.sets,
                    reps = planned.reps,
                    done = id?.let { doneOn(db, it, day) } ?: 0,
                    lastWeightKg = id?.let { lastWeight(db, it) },
                )
            }
        return Plan(chosen, day, entries)
    }

    private fun exerciseId(db: Db, name: String): Int? =
        db.selectOne("SELECT id FROM exercises WHERE lower(name) = lower(?)", listOf(name)) {
            it.int("id")
        }

    private fun doneOn(db: Db, exerciseId: Int, day: LocalDate): Int =
        db.selectOne(
            """
            SELECT COUNT(*) AS n
            FROM sets s JOIN workouts w ON w.id = s.workout_id
            WHERE s.exercise_id = ? AND s.is_warmup = 0 AND w.performed_on = ?
            """,
            listOf(exerciseId, day.toString()),
        ) { it.int("n") } ?: 0

    private fun lastWeight(db: Db, exerciseId: Int): Double? =
        db.selectOne(
            """
            SELECT s.weight_kg
            FROM sets s JOIN workouts w ON w.id = s.workout_id
            WHERE s.exercise_id = ? AND s.is_warmup = 0 AND s.weight_kg IS NOT NULL
            ORDER BY w.performed_on DESC, s.id DESC
            LIMIT 1
            """,
            listOf(exerciseId),
        ) { it.doubleOrNull("weight_kg") }
}
