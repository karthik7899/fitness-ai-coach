package dev.aura.core

import dev.aura.core.presentation.Store
import java.io.File
import java.time.LocalDate
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.DynamicTest
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.TestFactory

/**
 * Personal records against fixtures/records.json, the same cases
 * test_records.py runs; and the Log screen's other new pieces as
 * test_muscles.py pins them: correcting a set, and sets per muscle.
 */
class RecordsTest {

    private val day = LocalDate.of(2026, 3, 10)

    private val cases: List<JsonObject> by lazy {
        val fixtures = File(System.getProperty("aura.fixtures") ?: "../fixtures")
        Json.parseToJsonElement(File(fixtures, "records.json").readText())
            .jsonObject["cases"]!!.jsonArray.map { it.jsonObject }
    }

    private fun number(e: JsonElement): Double? = if (e is JsonNull) null else e.jsonPrimitive.doubleOrNull

    private fun pair(e: JsonElement): Pair<Double?, Int?> {
        val (w, r) = e.jsonArray
        return number(w) to number(r)?.toInt()
    }

    @TestFactory
    fun `the rule matches its specification`(): List<DynamicTest> {
        assertTrue(cases.size >= 8, "records.json has too few cases")
        return cases.map { case ->
            DynamicTest.dynamicTest(case["name"]!!.jsonPrimitive.content) {
                val got = Records.beaten(case["before"]!!.jsonArray.map(::pair), pair(case["set"]!!))
                val expected =
                    case["expect"]!!.jsonArray.map { r ->
                        val (kind, value, previous) = r.jsonArray
                        Triple(kind.jsonPrimitive.content, number(value), number(previous))
                    }
                assertEquals(expected, got.map { Triple(it.kind.key, it.value, it.previous) })
            }
        }
    }

    @Test
    fun `a logged set is checked against everything before it`() =
        JdbcDb.inMemory().use { db ->
            db.seedExercises()
            val store = Store(db)
            store.addSet("Back Squat", 100.0, 5, day = day.minusDays(7))
            val warmup = store.addSet("Back Squat", 140.0, 3, isWarmup = true, day = day)
            val first = store.addSet("Back Squat", 102.5, 5, day = day)
            val second = store.addSet("Back Squat", 102.5, 5, day = day)

            val (name, found) = store.records(first)!!
            assertEquals("Back Squat", name)
            assertEquals(listOf(Record.Kind.WEIGHT, Record.Kind.E1RM), found.map { it.kind })
            // The second matches the first, and the first is now what it has to beat.
            assertEquals(emptyList(), store.records(second)!!.second)
            assertEquals(emptyList(), store.records(warmup)!!.second)
            assertNull(store.records(999_999))
        }

    @Test
    fun `a set can be corrected`() =
        JdbcDb.inMemory().use { db ->
            db.seedExercises()
            val store = Store(db)
            val id = store.addSet("Bench Press", 80.0, 8, day = day)
            store.updateSet(id, 82.5, 7, 9.0, isWarmup = false)

            val set = store.log(day).sets.single()
            assertEquals(Triple(82.5, 7, 9.0), Triple(set.weightKg, set.reps, set.rpe))
            assertFailsWith<IllegalArgumentException> { store.updateSet(id, 80.0, 8, 11.0, false) }
        }

    @Test
    fun `sets count for each primary muscle within seven days`() =
        JdbcDb.inMemory().use { db ->
            db.seedExercises()
            db.addWorkout(day.minusDays(7), List(5) { SetSpec("Back Squat", 100.0, 5) })
            db.addWorkout(day.minusDays(6), List(4) { SetSpec("Back Squat", 100.0, 5) })
            db.addWorkout(
                day,
                listOf(SetSpec("Back Squat", 60.0, 5, warmup = true)) +
                    List(12) { SetSpec("Bench Press", 80.0, 8) } +
                    SetSpec("Sled Push", 50.0, 1),
            )

            val rows = Muscles.lastSevenDays(db, day)
            val got = rows.associateBy { it.muscle }
            assertEquals(4 to 4, got.getValue("quads").sets to got.getValue("glutes").sets)
            assertEquals(MuscleSets.Status.ON_TARGET, got.getValue("chest").status)
            assertEquals(12, got.getValue("chest").sets)
            assertEquals(MuscleSets.Status.UNDER, got.getValue("quads").status)
            assertEquals(1, got.getValue("Conditioning").sets)
            assertEquals(Muscles.targets.major, rows.take(Muscles.targets.major.size).map { it.muscle })
            assertEquals(0, got.getValue("calves").sets)
            assertEquals("Upper back", got.getValue("upper_back").label)
            assertEquals(10 to 20, Muscles.targets.min to Muscles.targets.max)
        }
}
