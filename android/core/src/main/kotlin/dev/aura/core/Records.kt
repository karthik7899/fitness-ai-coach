package dev.aura.core

import kotlin.math.round

/** A personal record one set broke: what kind, the new best, and the old one. */
data class Record(val kind: Kind, val value: Double, val previous: Double) {
    enum class Kind(val key: String) {
        WEIGHT("weight"),
        E1RM("e1rm"),
        REPS("reps"),
    }
}

/**
 * Personal records: whether a set just logged beat everything before it.
 *
 * The port of app/records.py, held to the same cases in fixtures/records.json:
 * heaviest weight, best estimated 1RM (Epley, as v_sets_enriched), and most
 * reps at this weight or heavier, which only counts where such a set exists.
 * A first set is no record. Warmups are neither checked nor counted.
 */
object Records {

    fun e1rm(weightKg: Double?, reps: Int?): Double? {
        if (weightKg == null || weightKg <= 0 || reps == null || reps !in 1..12) return null
        return round(weightKg * (1 + reps / 30.0) * 100) / 100
    }

    /** The records [new] sets over [before], in the order weight, e1rm, reps. */
    fun beaten(before: List<Pair<Double?, Int?>>, new: Pair<Double?, Int?>): List<Record> {
        val reps = new.second
        if (before.isEmpty() || reps == null) return emptyList()
        val weight = new.first ?: 0.0
        val found = mutableListOf<Record>()

        val heaviest = before.maxOf { it.first ?: 0.0 }
        if (weight > 0 && weight > heaviest) found += Record(Record.Kind.WEIGHT, weight, heaviest)

        val mine = e1rm(new.first, reps)
        val best = before.mapNotNull { e1rm(it.first, it.second) }.maxOrNull()
        if (mine != null && best != null && mine > best) found += Record(Record.Kind.E1RM, mine, best)

        val atOrAbove = before.filter { (it.first ?: 0.0) >= weight }.map { it.second ?: 0 }
        if (atOrAbove.isNotEmpty() && reps > atOrAbove.max()) {
            found += Record(Record.Kind.REPS, reps.toDouble(), atOrAbove.max().toDouble())
        }
        return found
    }

    /**
     * The exercise's name and the records this set broke, or null if there is
     * no such set. "Earlier" is an earlier day, or the same day and logged
     * first, as records.for_set.
     */
    fun forSet(db: Db, setId: Int): Pair<String, List<Record>>? {
        val id = setId.toString()
        data class Logged(val exerciseId: Int, val day: String, val name: String, val weight: Double?, val reps: Int?, val warmup: Boolean)
        val set =
            db.selectOne(
                """
                SELECT s.exercise_id, w.performed_on, e.name, s.weight_kg, s.reps, s.is_warmup
                FROM sets s
                JOIN workouts w ON w.id = s.workout_id
                JOIN exercises e ON e.id = s.exercise_id
                WHERE s.id = CAST(? AS INTEGER)
                """,
                listOf(id),
            ) {
                Logged(
                    it.int("exercise_id"),
                    it.string("performed_on"),
                    it.string("name"),
                    it.doubleOrNull("weight_kg"),
                    it.longOrNull("reps")?.toInt(),
                    it.boolean("is_warmup"),
                )
            } ?: return null
        if (set.warmup) return set.name to emptyList()

        val before =
            db.select(
                """
                SELECT s.weight_kg, s.reps
                FROM sets s JOIN workouts w ON w.id = s.workout_id
                WHERE s.exercise_id = CAST(? AS INTEGER) AND s.is_warmup = 0
                  AND s.id <> CAST(? AS INTEGER)
                  AND (w.performed_on < ? OR (w.performed_on = ? AND s.id < CAST(? AS INTEGER)))
                """,
                listOf(set.exerciseId.toString(), id, set.day, set.day, id),
            ) { it.doubleOrNull("weight_kg") to it.longOrNull("reps")?.toInt() }
        return set.name to beaten(before, set.weight to set.reps)
    }
}
