package dev.aura.core

import kotlin.test.assertEquals
import kotlin.test.assertTrue
import org.junit.jupiter.api.Test

class SchemaTest {

    @Test
    fun `every statement is a CREATE`() {
        val statements = Schema.statements()
        assertTrue(statements.isNotEmpty(), "schema.sql produced no statements")
        val odd = statements.filterNot { it.startsWith("CREATE ") }
        assertEquals(
            emptyList(),
            odd.map { it.take(60) },
            "Splitting on ';' produced a fragment, so a literal must now contain one.",
        )
    }

    @Test
    fun `the schema carries every metrics view`() {
        JdbcDb.inMemory().use { db ->
            val views =
                db.select(
                    "SELECT name FROM sqlite_master WHERE type = 'view' ORDER BY name"
                ) { it.string("name") }
            assertEquals(
                listOf(
                    "v_daily_load",
                    "v_daily_metrics_preferred",
                    "v_daily_volume",
                    "v_exercise_e1rm_daily",
                    "v_sets_enriched",
                    "v_training_load",
                    "v_weekly_muscle_volume",
                ),
                views,
            )
        }
    }

    @Test
    fun `foreign keys cascade, so deleting a workout takes its sets`() {
        JdbcDb.inMemory().use { db ->
            db.seedExercises()
            val workout = db.addWorkout(TODAY, listOf(SetSpec("Back Squat", 100.0, 5)))
            db.execute("DELETE FROM workouts WHERE id = ?", listOf(workout))
            val orphans = db.selectOne("SELECT COUNT(*) AS n FROM sets") { it.int("n") }
            assertEquals(0, orphans, "ON DELETE CASCADE did not fire; PRAGMA foreign_keys is off")
        }
    }
}
