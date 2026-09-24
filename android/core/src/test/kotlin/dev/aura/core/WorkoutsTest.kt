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
 * same templates, the same exercises created or reused by alias, and the same
 * progress counted.
 */
class WorkoutsTest {

    private val day = LocalDate.of(2026, 3, 10)

    private fun <T> withDb(block: (Db) -> T): T =
        JdbcDb.inMemory().use { db ->
            db.seedExercises()
            block(db)
        }

    private fun Plan.entry(planned: String) = entries.first { it.planned == planned }

    private fun Db.addExercise(name: String): Int {
        execute("INSERT INTO exercises (name, category, modality) VALUES (?, 'Chest', 'weight_reps')", listOf(name))
        return lastInsertRowId()
    }

    @Test
    fun `there is one workout per body part`() {
        assertEquals(
            listOf("Chest", "Back", "Shoulders", "Legs", "Triceps", "Biceps"),
            Workouts.templates.map { it.name },
        )
        assertTrue(Workouts.templates.all { t -> t.exercises.all { it.sets > 0 && it.repsMin in 1 until it.repsMax } })
    }

    @Test
    fun `names compare without case, spaces or punctuation`() {
        assertEquals("pullup", Workouts.normalise("Pull-Up"))
        assertEquals(Workouts.normalise("pull up"), Workouts.normalise("Pullup"))
        assertEquals(Workouts.normalise("EZ-Bar Curl"), Workouts.normalise("ez bar curl"))
    }

    @Test
    fun `starting creates missing exercises with their muscles`() = withDb { db ->
        Workouts.start(db, "back", day)

        val muscles =
            db.select(
                """
                SELECT m.muscle FROM exercise_muscles m
                JOIN exercises e ON e.id = m.exercise_id
                WHERE e.name = 'Barbell Row' ORDER BY m.muscle
                """
            ) { it.string("muscle") }
        assertEquals(listOf("lats", "upper_back"), muscles)
    }

    @Test
    fun `starting leaves an existing exercise alone`() = JdbcDb.inMemory().use { db ->
        db.execute(
            "INSERT INTO exercises (name, category, modality) VALUES ('back squat', 'Squats', 'weight_reps')"
        )
        Workouts.start(db, "legs", day)

        val squats =
            db.select("SELECT category FROM exercises WHERE lower(name) = 'back squat'") {
                it.string("category")
            }
        assertEquals(listOf("Squats"), squats)
    }

    @Test
    fun `an alias is used instead of creating a duplicate`() = JdbcDb.inMemory().use { db ->
        val imported = db.addExercise("Flat Barbell Bench Press")
        db.addWorkout(day.minusDays(3), listOf(SetSpec("Flat Barbell Bench Press", 80.0, 8)))

        val plan = assertNotNull(Workouts.start(db, "chest", day))

        val benches =
            db.select("SELECT name FROM exercises WHERE lower(name) LIKE '%bench press'") {
                it.string("name")
            }
        assertFalse("Bench Press" in benches)
        val first = plan.entries.first()
        assertEquals("Bench Press", first.planned)
        assertEquals("Flat Barbell Bench Press", first.exercise)
        assertEquals(80.0, first.lastWeightKg)
        assertEquals(imported to "Flat Barbell Bench Press", Workouts.resolve(db, "Bench Press"))
    }

    @Test
    fun `where several names exist the one with history wins`() = JdbcDb.inMemory().use { db ->
        db.addExercise("Bench Press")
        val imported = db.addExercise("Flat Barbell Bench Press")
        db.addWorkout(day.minusDays(5), listOf(SetSpec("Bench Press", 60.0, 8)))
        db.addWorkout(
            day.minusDays(3),
            listOf(SetSpec("Flat Barbell Bench Press", 80.0, 8), SetSpec("Flat Barbell Bench Press", 80.0, 8)),
        )
        assertEquals(imported, Workouts.resolve(db, "Bench Press")?.first)
    }

    @Test
    fun `with no history the template's own name wins`() = JdbcDb.inMemory().use { db ->
        db.addExercise("Barbell Bench Press")
        db.addExercise("Bench Press")
        assertEquals("Bench Press", Workouts.resolve(db, "Bench Press")?.second)
    }

    // ----------------------------------------------------------------------
    // Merging duplicates, as test_workouts.py
    // ----------------------------------------------------------------------

    private fun Db.importedWorkout(day: LocalDate, exercise: String, weight: Double, reps: Int) {
        execute(
            "INSERT INTO workouts (performed_on, source, external_id) VALUES (?, 'fitnotes', ?)",
            listOf(day.toString(), day.toString()),
        )
        val workout = lastInsertRowId()
        val exerciseId =
            selectOne("SELECT id FROM exercises WHERE name = ?", listOf(exercise)) { it.int("id") }!!
        execute(
            "INSERT INTO sets (workout_id, exercise_id, position, weight_kg, reps, is_warmup) VALUES (?, ?, 1, ?, ?, 0)",
            listOf(workout, exerciseId, weight, reps),
        )
    }

    private fun Db.muscles(id: Int): List<String> =
        select("SELECT muscle FROM exercise_muscles WHERE exercise_id = CAST(? AS INTEGER) ORDER BY muscle", listOf(id.toString())) {
            it.string("muscle")
        }

    /** "Bench Press" from an earlier workout beside the imported, muscle-less original. */
    private fun Db.duplicated(): Pair<Int, Int> {
        val fresh = addExercise("Bench Press")
        execute("INSERT INTO exercise_muscles (exercise_id, muscle) VALUES (?, 'chest'), (?, 'triceps')", listOf(fresh, fresh))
        execute("INSERT INTO exercises (name, modality) VALUES ('Flat Barbell Bench Press', 'weight_reps')")
        val imported = lastInsertRowId()
        addWorkout(day, listOf(SetSpec("Bench Press", 80.0, 8), SetSpec("Bench Press", 80.0, 8)))
        importedWorkout(day.minusDays(3), "Flat Barbell Bench Press", 77.5, 8)
        return fresh to imported
    }

    @Test
    fun `duplicates are found and the imported one is kept`() = JdbcDb.inMemory().use { db ->
        val (fresh, imported) = db.duplicated()
        val merge = Workouts.duplicates(db).single()
        // Imported history wins even though the other has more sets.
        assertEquals(imported, merge.keep.id)
        assertEquals(listOf(fresh), merge.drop.map { it.id })
    }

    @Test
    fun `merging moves the sets and deletes the duplicate`() = JdbcDb.inMemory().use { db ->
        val (fresh, imported) = db.duplicated()
        assertEquals(1, Workouts.mergeDuplicates(db).size)

        assertNull(db.selectOne("SELECT id FROM exercises WHERE id = CAST(? AS INTEGER)", listOf(fresh.toString())) { it.int("id") })
        assertEquals(
            3,
            db.selectOne("SELECT COUNT(*) AS n FROM sets WHERE exercise_id = CAST(? AS INTEGER)", listOf(imported.toString())) { it.int("n") },
        )
        assertEquals(listOf("chest", "triceps"), db.muscles(imported))
        assertEquals(
            "Chest",
            db.selectOne("SELECT category FROM exercises WHERE id = CAST(? AS INTEGER)", listOf(imported.toString())) { it.string("category") },
        )
        assertTrue(Workouts.duplicates(db).isEmpty())
    }

    @Test
    fun `the kept exercise keeps its own muscles`() = JdbcDb.inMemory().use { db ->
        val kept = db.addExercise("Barbell Squat")
        db.execute("INSERT INTO exercise_muscles (exercise_id, muscle) VALUES (?, 'quads')", listOf(kept))
        val other = db.addExercise("Back Squat")
        db.execute("INSERT INTO exercise_muscles (exercise_id, muscle) VALUES (?, 'glutes')", listOf(other))
        db.importedWorkout(day, "Barbell Squat", 100.0, 5)

        Workouts.mergeDuplicates(db)
        assertEquals(listOf("quads"), db.muscles(kept))
    }

    @Test
    fun `names that only look alike are not merged`() = JdbcDb.inMemory().use { db ->
        db.addExercise("Bench Press")
        db.addExercise("Incline Bench Press")
        assertTrue(Workouts.duplicates(db).isEmpty())
    }

    @Test
    fun `a merge that fails part-way changes nothing`() = JdbcDb.inMemory().use { db ->
        db.duplicated()
        val before = db.select("SELECT id, exercise_id FROM sets ORDER BY id") { it.int("id") to it.int("exercise_id") }
        val failing = object : Db by db {
            override fun execute(sql: String, args: List<Any?>) {
                if (sql.startsWith("DELETE FROM exercises")) error("disk full")
                db.execute(sql, args)
            }
            override fun <T> transaction(block: () -> T): T = db.transaction(block)
        }
        kotlin.runCatching { Workouts.mergeDuplicates(failing) }
        assertEquals(before, db.select("SELECT id, exercise_id FROM sets ORDER BY id") { it.int("id") to it.int("exercise_id") })
        assertEquals(1, Workouts.duplicates(db).size)
    }

    @Test
    fun `the screens list duplicates and merge them`() = JdbcDb.inMemory().use { db ->
        db.duplicated()
        val store = Store(db)
        assertEquals("Flat Barbell Bench Press", store.settings().duplicates.single().keep.name)
        assertEquals(1, store.mergeDuplicates())
        assertTrue(store.settings().duplicates.isEmpty())
    }

    @Test
    fun `an unknown template starts nothing`() = withDb { db ->
        assertNull(Workouts.start(db, "no-such-thing", day))
        assertNull(Workouts.plan(db, day))
    }

    @Test
    fun `progress counts today's working sets`() = withDb { db ->
        Workouts.start(db, "legs", day)
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
        assertEquals("legs", plan.template.id)
        assertEquals(2, plan.entry("Back Squat").done)
        assertEquals(0, plan.entry("Leg Press").done)
        assertFalse(plan.complete)
    }

    @Test
    fun `last weight is the most recent working set`() = withDb { db ->
        Workouts.start(db, "legs", day)
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
        assertNull(plan.entry("Leg Press").lastWeightKg)
    }

    @Test
    fun `the target comes from the last session, and today's sets do not move it`() = withDb { db ->
        Workouts.start(db, "legs", day)
        // Legs plans Back Squat 4 × 5–8. Last time: all four sets of 8 at 100.
        db.addWorkout(day.minusDays(4), List(4) { SetSpec("Back Squat", 100.0, 8) })

        val squat = assertNotNull(Workouts.plan(db, day)).entry("Back Squat")
        assertEquals(Suggestion(Advice.UP, 105.0, 5), squat.target)
        assertEquals(180, squat.restS)
        assertEquals(5 to 8, squat.repsMin to squat.repsMax)

        db.addWorkout(day, listOf(SetSpec("Back Squat", 105.0, 5)))
        assertEquals(105.0, assertNotNull(Workouts.plan(db, day)).entry("Back Squat").target.weightKg)
        assertEquals(
            Suggestion(Advice.NEW, null, 8),
            assertNotNull(Workouts.plan(db, day)).entry("Leg Press").target,
        )
    }

    @Test
    fun `effort is recorded with the set and read by the rule`() = withDb { db ->
        val store = Store(db)
        store.startWorkout("legs", day)
        repeat(4) { store.addSet("Back Squat", 100.0, 8, day = day.minusDays(4), rpe = if (it == 3) 10.0 else 8.0) }

        assertEquals(10.0, store.log(day.minusDays(4)).sets.last().rpe)
        // The last set was a grind, so the weight holds.
        assertEquals(Advice.REPEAT, assertNotNull(store.log(day).plan).entry("Back Squat").target.advice)
    }

    @Test
    fun `a plan lasts only the day it was started, and finishing clears it`() = withDb { db ->
        Workouts.start(db, "legs", day)
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
            listOf("""{"template": "shoulders", "day": "$day"}"""),
        )
        assertEquals("shoulders", Workouts.plan(db, day)?.template?.id)
    }
}
