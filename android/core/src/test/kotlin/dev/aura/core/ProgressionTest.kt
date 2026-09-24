package dev.aura.core

import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.DynamicTest
import org.junit.jupiter.api.TestFactory

/**
 * The progression rule against fixtures/progression.json, the same cases
 * test_progression.py runs against the Python original.
 */
class ProgressionTest {

    private val cases: List<JsonObject> by lazy {
        val fixtures = File(System.getProperty("aura.fixtures") ?: "../fixtures")
        Json.parseToJsonElement(File(fixtures, "progression.json").readText())
            .jsonObject["cases"]!!.jsonArray.map { it.jsonObject }
    }

    private fun number(e: kotlinx.serialization.json.JsonElement): Double? =
        if (e is JsonNull) null else e.jsonPrimitive.doubleOrNull

    @TestFactory
    fun `the rule matches its specification`(): List<DynamicTest> {
        assertTrue(cases.size >= 10, "progression.json has too few cases")
        return cases.map { case ->
            DynamicTest.dynamicTest(case["name"]!!.jsonPrimitive.content) {
                val last =
                    case["last"]!!.jsonArray.map { set ->
                        val (w, r, rpe) = set.jsonArray
                        DoneSet(number(w), number(r)?.toInt(), number(rpe))
                    }
                val got =
                    Progression.suggest(
                        last,
                        case["sets"]!!.jsonPrimitive.int,
                        case["reps_min"]!!.jsonPrimitive.int,
                        case["reps_max"]!!.jsonPrimitive.int,
                        case["increment"]!!.jsonPrimitive.doubleOrNull!!,
                    )
                val expect = case["expect"]!!.jsonObject
                assertEquals(expect["advice"]!!.jsonPrimitive.content, got.advice.key)
                assertEquals(number(expect["weight"]!!), got.weightKg)
                assertEquals(expect["reps"]!!.jsonPrimitive.int, got.reps)
            }
        }
    }
}
