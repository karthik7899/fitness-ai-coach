package dev.aura.core

import java.time.LocalDate
import kotlin.math.abs
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue
import org.junit.jupiter.api.Test

/**
 * The same assertions the Python suite makes about the same views.
 *
 * That duplication is the point: these are the numbers the coach quotes, and
 * this is what says the phone and the server agree about them.
 */
class MetricsTest {

    private fun withDb(block: (Db, Metrics) -> Unit) =
        JdbcDb.inMemory().use { db ->
            db.seedExercises()
            block(db, Metrics(db))
        }

    private fun assertClose(expected: Double, actual: Double?, tolerance: Double = 0.01) {
        assertNotNull(actual, "expected $expected but the value was null")
        assertTrue(
            abs(expected - actual) <= tolerance,
            "expected $expected but got $actual",
        )
    }

    private fun Db.e1rm(): Double? =
        selectOne("SELECT e1rm_kg FROM v_sets_enriched") { it.doubleOrNull("e1rm_kg") }

    @Test
    fun `Epley estimated 1RM`() = withDb { db, _ ->
        db.addWorkout(TODAY, listOf(SetSpec("Back Squat", 100.0, 5)))
        assertClose(116.67, db.e1rm()) // 100 * (1 + 5/30)
    }

    @Test
    fun `a single rep is barely above the weight`() = withDb { db, _ ->
        db.addWorkout(TODAY, listOf(SetSpec("Back Squat", 140.0, 1)))
        assertClose(144.67, db.e1rm())
    }

    @Test
    fun `no estimate outside the reliable rep range`() = withDb { db, _ ->
        // Unguarded, these formulas produce nonsense; Brzycki goes negative past ~37.
        listOf(0, 13, 20, 40).forEach { reps ->
            JdbcDb.inMemory().use { fresh ->
                fresh.seedExercises()
                fresh.addWorkout(TODAY, listOf(SetSpec("Back Squat", 60.0, reps)))
                assertNull(fresh.e1rm(), "$reps reps should not produce an estimate")
            }
        }
    }

    @Test
    fun `a bodyweight set has no estimate`() = withDb { db, _ ->
        db.addWorkout(TODAY, listOf(SetSpec("Back Squat", 0.0, 10)))
        assertNull(db.e1rm())
    }

    @Test
    fun `warmup sets do not inflate volume`() = withDb { db, metrics ->
        db.addWorkout(
            TODAY,
            listOf(
                SetSpec("Back Squat", 60.0, 10, warmup = true),
                SetSpec("Back Squat", 100.0, 5),
                SetSpec("Back Squat", 100.0, 5),
            ),
        )
        val day = metrics.volumeByDay(TODAY, TODAY).single()
        assertClose(1000.0, day.volumeKg)
        assertEquals(2, day.workingSets)
    }

    @Test
    fun `a warmup-only day has no muscle volume at all`() = withDb { db, metrics ->
        db.addWorkout(TODAY, listOf(SetSpec("Bench Press", 40.0, 20, warmup = true)))
        assertEquals(emptyList(), metrics.volumeByMuscle(TODAY.minusDays(7), TODAY))
    }

    @Test
    fun `volume is credited to every primary muscle, not split between them`() =
        withDb { db, metrics ->
            db.addWorkout(TODAY, listOf(SetSpec("Back Squat", 100.0, 5)))
            val byMuscle = metrics.volumeByMuscle(TODAY.minusDays(7), TODAY).sortedBy { it.muscle }
            assertEquals(listOf("glutes", "quads"), byMuscle.map { it.muscle })
            byMuscle.forEach { assertClose(500.0, it.volumeKg) }
        }

    @Test
    fun `an unmapped exercise falls back to its category`() = withDb { db, metrics ->
        db.addWorkout(TODAY, listOf(SetSpec("Sled Push", 80.0, 8)))
        val byMuscle = metrics.volumeByMuscle(TODAY.minusDays(7), TODAY)
        assertEquals(listOf("Conditioning"), byMuscle.map { it.muscle })
        assertClose(640.0, byMuscle.single().volumeKg)
    }

    @Test
    fun `progression reports the best set of the day`() = withDb { db, metrics ->
        db.addWorkout(
            TODAY,
            listOf(
                SetSpec("Back Squat", 90.0, 5),
                SetSpec("Back Squat", 110.0, 3),
                SetSpec("Back Squat", 100.0, 5),
            ),
        )
        val day = metrics.exerciseProgression("back squat", TODAY.minusDays(7), TODAY).single()
        assertClose(110.0, day.topWeightKg)
        assertClose(121.0, day.bestE1rmKg)
    }

    @Test
    fun `rest days count as a real zero`() = withDb { db, metrics ->
        val start = TODAY.minusDays(6)
        db.addWorkout(start, listOf(SetSpec("Back Squat", 100.0, 10)))
        val days = metrics.trainingLoad(start, TODAY)
        assertEquals(7, days.size, "every calendar day should be present, not just training days")
        assertClose(1.0, days.first().loadAu)
        assertTrue(days.drop(1).all { it.loadAu == 0.0 })
    }

    @Test
    fun `ACWR is acute over chronic`() = withDb { db, metrics ->
        for (offset in 0 until 28 step 2) {
            db.addWorkout(TODAY.minusDays(offset.toLong()), listOf(SetSpec("Back Squat", 100.0, 10)))
        }
        val today = metrics.trainingLoad(TODAY, TODAY).single()
        assertClose(today.acute7d / today.chronic28d, today.acwr)
    }

    @Test
    fun `ACWR is null without history`() = withDb { _, metrics ->
        assertNull(metrics.trainingLoad(TODAY, TODAY).single().acwr)
    }

    @Test
    fun `two devices reporting steps do not double count`() = withDb { db, metrics ->
        db.addDailyMetric(TODAY, "steps", "health_connect", 9000.0, "count")
        db.addDailyMetric(TODAY, "steps", "gadgetbridge", 8000.0, "count")
        db.addDailyMetric(TODAY, "steps", "manual", 10000.0, "count")

        val steps = metrics.dailyMetrics(TODAY, TODAY).filter { it.metric == "steps" }
        assertEquals(1, steps.size)
        assertEquals("manual", steps.single().source)
        assertClose(10000.0, steps.single().value)
    }

    @Test
    fun `cardio contributes to load`() = withDb { db, metrics ->
        db.execute(
            """
            INSERT INTO activities (source, external_id, sport_type, started_at,
                                    distance_m, moving_time_s)
            VALUES ('strava', 'a1', 'Run', ?, 10000, 3000)
            """,
            listOf("$TODAY 09:00:00"),
        )
        val today = metrics.trainingLoad(TODAY, TODAY).single()
        assertClose(50.0, today.cardioMinutes)
        assertClose(10.0, today.cardioKm)
        assertClose(5.0, today.loadAu) // tonnes + minutes/10
    }

    @Test
    fun `the dashboard summary pulls from every view at once`() = withDb { db, metrics ->
        db.addWorkout(TODAY, listOf(SetSpec("Back Squat", 100.0, 5)))
        db.addDailyMetric(TODAY, "steps", "gadgetbridge", 6000.0, "count")

        val summary = metrics.summary()
        assertClose(6000.0, summary.latestMetrics["steps"]?.value)
        assertClose(0.5, summary.load?.loadAu) // 500kg = 0.5 tonnes
        assertEquals(listOf<LocalDate>(TODAY), summary.recentWorkouts.map { it.date })
    }
}
