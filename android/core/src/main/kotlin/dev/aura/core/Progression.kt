package dev.aura.core

import kotlin.math.floor
import kotlin.math.round

/** One working set of an earlier session, as the rule reads it. */
data class DoneSet(val weightKg: Double?, val reps: Int?, val rpe: Double?)

/** Today's target for one exercise, and which way it moved. */
data class Suggestion(val advice: Advice, val weightKg: Double?, val reps: Int)

enum class Advice(val key: String) {
    NEW("new"),
    UP("up"),
    REPEAT("repeat"),
    DOWN("down"),
}

/**
 * What to lift next time: double progression over a rep range.
 *
 * The port of app/progression.py, held to the same cases in
 * fixtures/progression.json:
 *
 * - UP: every planned set at the top weight reached the top of the range and
 *   none was a grind (RPE 10). Add one increment, back to the bottom.
 * - DOWN: even the best set at that weight fell short of the bottom. Drop
 *   about ten percent, rounded down to a loadable weight.
 * - REPEAT: anything between. Same weight, one more rep on the weakest set.
 * - NEW: no history. The bottom of the range; the weight is the trainee's call.
 *
 * Bodyweight sets progress in reps; at the top of the range the advice is UP
 * with no weight, meaning add load.
 */
object Progression {

    private const val GRIND_RPE = 10.0
    private const val DROP = 0.9

    // The epsilon keeps 90.00000000000001 / 2.5 from flooring to 35.
    private fun roundDown(value: Double, step: Double): Double =
        round3(floor(value / step + 1e-9) * step)

    private fun round3(value: Double): Double = round(value * 1000) / 1000

    fun suggest(last: List<DoneSet>, sets: Int, repsMin: Int, repsMax: Int, increment: Double): Suggestion {
        val done = last.filter { it.reps != null }
        if (done.isEmpty()) return Suggestion(Advice.NEW, null, repsMin)

        val top = done.mapNotNull { it.weightKg }.maxOrNull()
        val atTop = done.filter { it.weightKg == top }
        val lowest = atTop.minOf { it.reps!! }
        val best = atTop.maxOf { it.reps!! }
        val grind = atTop.any { (it.rpe ?: 0.0) >= GRIND_RPE }

        if (atTop.size >= sets && lowest >= repsMax && !grind) {
            return if (top == null) Suggestion(Advice.UP, null, repsMax)
            else Suggestion(Advice.UP, round3(top + increment), repsMin)
        }
        if (best < repsMin && top != null) {
            return Suggestion(Advice.DOWN, roundDown(top * DROP, increment), repsMin)
        }
        return Suggestion(Advice.REPEAT, top, maxOf(repsMin, minOf(lowest + 1, repsMax)))
    }
}
