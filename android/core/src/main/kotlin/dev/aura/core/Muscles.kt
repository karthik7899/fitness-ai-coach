package dev.aura.core

import java.time.LocalDate
import kotlinx.serialization.Serializable

/** The weekly target, exported with the starter workouts from app/muscles.py. */
@Serializable
data class MuscleTargets(val min: Int, val max: Int, val major: List<String>)

/** One muscle's working sets over the last seven days, and where that sits. */
data class MuscleSets(val muscle: String, val label: String, val sets: Int, val status: Status) {
    enum class Status { UNDER, ON_TARGET, OVER }
}

/**
 * Working sets per muscle over the last seven days, as app/muscles.py counts
 * them: once for each primary muscle, the category standing in where an
 * exercise has none. A rolling week, so a Monday does not read as everything
 * under target.
 */
object Muscles {

    val targets: MuscleTargets
        get() = Workouts.muscleTargets

    fun status(sets: Int): MuscleSets.Status =
        when {
            sets < targets.min -> MuscleSets.Status.UNDER
            sets > targets.max -> MuscleSets.Status.OVER
            else -> MuscleSets.Status.ON_TARGET
        }

    fun label(muscle: String): String = muscle.replace('_', ' ').replaceFirstChar { it.uppercase() }

    /** Each major muscle in a fixed order, even at zero, then any other trained, by sets. */
    fun lastSevenDays(db: Db, today: LocalDate): List<MuscleSets> {
        val counted =
            db.select(
                """
                SELECT COALESCE(m.muscle, v.category, 'Uncategorised') AS muscle,
                       COUNT(*) AS sets
                FROM v_sets_enriched v
                LEFT JOIN exercise_muscles m
                       ON m.exercise_id = v.exercise_id AND m.is_primary
                WHERE NOT v.is_warmup AND v.performed_on BETWEEN ? AND ?
                GROUP BY COALESCE(m.muscle, v.category, 'Uncategorised')
                """,
                listOf(today.minusDays(6).toString(), today.toString()),
            ) { it.string("muscle") to it.int("sets") }.toMap()
        val others =
            counted.keys.filter { it !in targets.major }
                .sortedWith(compareByDescending<String> { counted.getValue(it) }.thenBy { it })
        return (targets.major + others).map { muscle ->
            val sets = counted[muscle] ?: 0
            MuscleSets(muscle, label(muscle), sets, status(sets))
        }
    }
}
