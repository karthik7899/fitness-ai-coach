package dev.aura.core

import java.time.LocalDate
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

/** One exercise in a template, with its target. */
@Serializable
data class Planned(
    val exercise: String,
    val sets: Int,
    @kotlinx.serialization.SerialName("reps_min") val repsMin: Int,
    @kotlinx.serialization.SerialName("reps_max") val repsMax: Int,
)

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
    @kotlinx.serialization.SerialName("increment_kg") val incrementKg: Double = 2.5,
    @kotlinx.serialization.SerialName("rest_s") val restS: Int = 120,
)

/** Where one exercise of today's plan stands. */
data class PlanEntry(
    /** The exercise as it exists here, which may be an alias of [planned]. */
    val exercise: String,
    /** The template's name for it. */
    val planned: String,
    val sets: Int,
    val repsMin: Int,
    val repsMax: Int,
    /** Working sets of it logged today, from any source. */
    val done: Int,
    /** The most recent working weight, today's included. */
    val lastWeightKg: Double?,
    /** What to aim for today, from the last session before it. */
    val target: Suggestion,
    /** Rest between its sets, in seconds. */
    val restS: Int,
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
        @kotlinx.serialization.SerialName("muscle_targets") val muscleTargets: MuscleTargets,
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

    val muscleTargets: MuscleTargets
        get() = document.muscleTargets

    fun template(id: String): Template? = templates.firstOrNull { it.id == id }

    private val notAlphanumeric = Regex("[^a-z0-9]+")

    /** "Pull-Up", "pull up" and "Pullup" compare equal, as in workouts.normalise. */
    fun normalise(name: String): String = notAlphanumeric.replace(name.lowercase(), "")

    /** The template's name for an exercise, then its aliases, in preference order. */
    fun namesFor(exercise: String): List<String> {
        val entry = document.catalogue.firstOrNull { it.name.equals(exercise, ignoreCase = true) }
        return listOf(exercise) + entry?.aliases.orEmpty()
    }

    /** An existing exercise, with what counts when choosing between its names. */
    data class Candidate(val id: Int, val name: String, val sets: Int, val imported: Int, val rank: Int)

    // Imported history first, then the most working sets, then the earlier
    // name in the alias list, then the older row. As workouts.Candidate.key.
    private val best: Comparator<Candidate> =
        compareByDescending<Candidate> { it.imported > 0 }
            .thenByDescending { it.sets }
            .thenBy { it.rank }
            .thenBy { it.id }

    private fun existing(db: Db): List<Candidate> =
        db.select(
            """
            SELECT e.id, e.name,
                   COUNT(s.id) AS sets,
                   COUNT(CASE WHEN w.source <> 'manual' THEN s.id END) AS imported
            FROM exercises e
            LEFT JOIN sets s ON s.exercise_id = e.id AND s.is_warmup = 0
            LEFT JOIN workouts w ON w.id = s.workout_id
            GROUP BY e.id, e.name
            """
        ) { Candidate(it.int("id"), it.string("name"), it.int("sets"), it.int("imported"), -1) }

    private fun candidates(existing: List<Candidate>, exercise: String): List<Candidate> {
        val rank = HashMap<String, Int>()
        namesFor(exercise).forEachIndexed { i, name -> rank.putIfAbsent(normalise(name), i) }
        return existing
            .mapNotNull { c -> rank[normalise(c.name)]?.let { c.copy(rank = it) } }
            .sortedWith(best)
    }

    /**
     * The existing exercise a template's exercise means, as (id, name).
     *
     * Any exercise under its name or an alias counts. When several do, the
     * imported one wins, then the one with the most working sets, since that
     * is where the history is. The same rule as workouts.resolve.
     */
    fun resolve(db: Db, exercise: String): Pair<Int, String>? =
        candidates(existing(db), exercise).firstOrNull()?.let { it.id to it.name }

    /** A catalogue exercise found under more than one of its names. */
    data class Merge(val keep: Candidate, val drop: List<Candidate>)

    /** Catalogue exercises that exist under more than one name, and which to keep. */
    fun duplicates(db: Db): List<Merge> {
        val all = existing(db)
        val claimed = HashSet<Int>()
        return document.catalogue.mapNotNull { entry ->
            val found = candidates(all, entry.name).filter { it.id !in claimed }
            if (found.size < 2) return@mapNotNull null
            claimed += found.map { it.id }
            Merge(found.first(), found.drop(1))
        }
    }

    /**
     * Fold each duplicate into the exercise [duplicates] chose to keep: its
     * sets move across and it is deleted. The kept exercise keeps its own
     * name, category and muscles, taking the duplicate's only where it has
     * none. All or nothing, as workouts.merge_duplicates.
     */
    fun mergeDuplicates(db: Db): List<Merge> =
        db.transaction {
            val merges = duplicates(db)
            for (merge in merges) {
                val keep = merge.keep.id
                for (drop in merge.drop.map { it.id }) {
                    db.execute("UPDATE sets SET exercise_id = ? WHERE exercise_id = ?", listOf(keep, drop))
                    db.execute(
                        """
                        INSERT INTO exercise_muscles (exercise_id, muscle, is_primary)
                        SELECT ?, muscle, is_primary FROM exercise_muscles
                        WHERE exercise_id = ?
                          AND NOT EXISTS (SELECT 1 FROM exercise_muscles WHERE exercise_id = ?)
                        """,
                        listOf(keep, drop, keep),
                    )
                    db.execute(
                        """
                        UPDATE exercises
                        SET category = (SELECT category FROM exercises WHERE id = ?)
                        WHERE id = ? AND category IS NULL
                        """,
                        listOf(drop, keep),
                    )
                    db.execute("DELETE FROM exercise_muscles WHERE exercise_id = ?", listOf(drop))
                    db.execute("DELETE FROM exercises WHERE id = ?", listOf(drop))
                }
            }
            merges
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
                val loading = document.catalogue.firstOrNull { it.name == planned.exercise }
                val increment = loading?.incrementKg ?: 2.5
                PlanEntry(
                    exercise = found?.second ?: planned.exercise,
                    planned = planned.exercise,
                    sets = planned.sets,
                    repsMin = planned.repsMin,
                    repsMax = planned.repsMax,
                    done = id?.let { doneOn(db, it, day) } ?: 0,
                    lastWeightKg = id?.let { lastWeight(db, it) },
                    // From the last session before today, so it holds steady
                    // through today's sets. As workouts.plan.
                    target =
                        Progression.suggest(
                            id?.let { previousSession(db, it, day) }.orEmpty(),
                            planned.sets,
                            planned.repsMin,
                            planned.repsMax,
                            increment,
                        ),
                    restS = loading?.restS ?: 120,
                )
            }
        return Plan(chosen, day, entries)
    }

    /** Each working set on the last day before [day], in the order done. */
    private fun previousSession(db: Db, exerciseId: Int, day: LocalDate): List<DoneSet> {
        val id = exerciseId.toString()
        val lastDay =
            db.selectOne(
                """
                SELECT MAX(w.performed_on) AS d
                FROM sets s JOIN workouts w ON w.id = s.workout_id
                WHERE s.exercise_id = CAST(? AS INTEGER) AND s.is_warmup = 0 AND w.performed_on < ?
                """,
                listOf(id, day.toString()),
            ) { it.stringOrNull("d") } ?: return emptyList()
        return db.select(
            """
            SELECT s.weight_kg, s.reps, s.rpe
            FROM sets s JOIN workouts w ON w.id = s.workout_id
            WHERE s.exercise_id = CAST(? AS INTEGER) AND s.is_warmup = 0 AND w.performed_on = ?
            ORDER BY w.id, s.position, s.id
            """,
            listOf(id, lastDay),
        ) { DoneSet(it.doubleOrNull("weight_kg"), it.longOrNull("reps")?.toInt(), it.doubleOrNull("rpe")) }
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
            WHERE s.exercise_id = CAST(? AS INTEGER) AND s.is_warmup = 0 AND w.performed_on = ?
            """,
            // Strings only: Android's rawQuery binds every argument as text.
            listOf(exerciseId.toString(), day.toString()),
        ) { it.int("n") } ?: 0

    private fun lastWeight(db: Db, exerciseId: Int): Double? =
        db.selectOne(
            """
            SELECT s.weight_kg
            FROM sets s JOIN workouts w ON w.id = s.workout_id
            WHERE s.exercise_id = CAST(? AS INTEGER) AND s.is_warmup = 0 AND s.weight_kg IS NOT NULL
            ORDER BY w.performed_on DESC, s.id DESC
            LIMIT 1
            """,
            listOf(exerciseId.toString()),
        ) { it.doubleOrNull("weight_kg") }
}
