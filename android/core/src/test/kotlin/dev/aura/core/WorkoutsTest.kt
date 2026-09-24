package dev.aura.core

import dev.aura.core.presentation.Store
import java.time.LocalDate
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue
import org.junit.jupiter.api.Test

/**
 * Starter workouts, as test_workouts.py pins them for the Python app: the
 * same templates, the same exercises created, and the same progress counted.
 */
class WorkoutsTest {

    private val day = LocalDate.of(2026, 3, 10)

    private fun <T> withDb(block: (Db) -> T): T =
        JdbcDb.inMemory().use { db ->
            db.seedExercises()
            block(db)
        }

    private fun Plan.entry(name: String) = entries.first { it.exercise == name }

    @Test
    fun `the generated templates load and use only catalogue exercises`() {
        val ids = Workouts.templates.map { it.id }
        assertEquals(listOf("full-body-a", "full-body-b", "push", "pull", "legs", "no-equipment"), ids)
        assertTrue(Workouts.templates.all { t -> t.exercises.all { it.sets > 0 && it.reps > 0 } })
    }

    @Test
    fun `starting creates missing exercises with their muscles`() = withDb { db ->
        Workouts.start(db, "full-body-a", day)

        val muscles =
            db.select(
                """
                SELECT m.muscle FROM exercise_muscles m
                JOIN exercises e ON e.id = m.exercise_id
                WHERE e.name = 'Barbell Row' ORDER BY m.muscle
                """
            ) { it.string("muscle") }
        assertEquals(listOf("lats", "upper_back"), muscles)
        assertEquals(
            "Back",
            db.selectOne("SELECT category FROM exercises WHERE name = 'Barbell Row'") {
                it.string("category")
            },
        )
    }

    @Test
    fun `starting leaves an existing exercise alone`() = JdbcDb.inMemory().use { db ->
        db.execute(
            "INSERT INTO exercises (name, category, modality) VALUES ('back squat', 'Squats', 'weight_reps')"
        )
        Workouts.start(db, "full-body-a", day)

        val squats =
            db.select("SELECT category FROM exercises WHERE lower(name) = 'back squat'") {
                it.string("category")
            }
        assertEquals(listOf("Squats"), squats)
    }

    @Test
    fun `an unknown template starts nothing`() = withDb { db ->
        assertNull(Workouts.start(db, "no-such-thing", day))
        assertNull(Workouts.plan(db, day))
    }

    @Test
    fun `progress counts today's working sets`() = withDb { db ->
        Workouts.start(db, "full-body-a", day)
        db.addWorkout(day.minusDays(2), listOf(SetSpec("Back Squat", 95.0, 5)))
        db.addWorkout(
            day,
            listOf(
                SetSpec("Back Squat", 60.0, 5, warmup = true),
                SetSpec("Back Squat", 100.0, 5),
                SetSpec("Back Squat", 100.0, 5),
                SetSpec("Bench Press", 70.0, 5),
            ),
        )

        val plan = assertNotNull(Workouts.plan(db, day))
        assertEquals("full-body-a", plan.template.id)
        assertEquals(2, plan.entry("Back Squat").done)
        assertEquals(1, plan.entry("Bench Press").done)
        assertEquals(0, plan.entry("Barbell Row").done)
        assertFalse(plan.complete)
    }

    @Test
    fun `last weight is the most recent working set`() = withDb { db ->
        Workouts.start(db, "full-body-a", day)
        db.addWorkout(day.minusDays(7), listOf(SetSpec("Back Squat", 90.0, 5)))
        db.addWorkout(
            day.minusDays(2),
            listOf(
                SetSpec("Back Squat", 95.0, 5),
                SetSpec("Back Squat", 97.5, 5),
                SetSpec("Back Squat", 50.0, 10, warmup = true),
            ),
        )

        val plan = assertNotNull(Workouts.plan(db, day))
        assertEquals(97.5, plan.entry("Back Squat").lastWeightKg)
        assertNull(plan.entry("Barbell Row").lastWeightKg)
    }

    @Test
    fun `a plan lasts only the day it was started, and finishing clears it`() = withDb { db ->
        Workouts.start(db, "full-body-a", day)
        assertNotNull(Workouts.plan(db, day))
        assertNull(Workouts.plan(db, day.plusDays(1)))

        Workouts.finish(db)
        assertNull(Workouts.plan(db, day))
    }

    @Test
    fun `the screens see the templates and today's plan`() = withDb { db ->
        val store = Store(db)
        assertNull(store.dashboard(day).activeTemplate)
        assertEquals(6, store.dashboard(day).templates.size)

        store.startWorkout("legs", day)
        assertEquals("legs", store.dashboard(day).activeTemplate)

        store.addSet("Back Squat", 100.0, 6, day = day)
        val plan = assertNotNull(store.log(day).plan)
        assertEquals(1, plan.entry("Back Squat").done)
        assertEquals(100.0, plan.entry("Back Squat").lastWeightKg)

        store.finishWorkout()
        assertNull(store.log(day).plan)
    }

    @Test
    fun `the desktop app's plan is read as the same plan`() = withDb { db ->
        // Exactly what settings_store.put writes for a plan started on the desktop.
        db.execute(
            "INSERT INTO app_settings (\"key\", value) VALUES ('workout', ?)",
            listOf("""{"template": "push", "day": "$day"}"""),
        )
        assertEquals("push", Workouts.plan(db, day)?.template?.id)
    }
}
