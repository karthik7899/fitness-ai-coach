package dev.aura.core

import dev.aura.core.agent.Answer
import dev.aura.core.agent.Coach
import dev.aura.core.agent.GroundingCheck
import dev.aura.core.agent.Transport
import java.io.File
import java.time.LocalDate
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.jupiter.api.DynamicTest
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.TestFactory

/**
 * The eval scenarios in evals/scenarios/, run through the Kotlin coach with
 * the model's side scripted — the same files test_evals.py runs through the
 * Python one.
 *
 * Nothing about the model is judged here. What a pass proves is that the
 * scenario's expected figures come out of the Kotlin tools on its seed data,
 * and that this harness passes the scripted answer: a scenario that passes in
 * Python and fails here is a difference between the two apps.
 */
class EvalTest {

    private val directory = File(System.getProperty("aura.evals") ?: "../../evals/scenarios")

    private val scenarios: List<Pair<String, JsonObject>> by lazy {
        (directory.listFiles { f -> f.extension == "json" } ?: emptyArray())
            .sortedBy { it.name }
            .map { file ->
                val raw = Json.parseToJsonElement(resolveDates(file.readText(), TODAY)).jsonObject
                raw.string("name") to raw
            }
    }

    @Test
    fun `the scenarios are found`() {
        assertTrue(scenarios.size >= 10, "No scenarios at ${directory.absolutePath}")
    }

    @TestFactory
    fun `each scripted scenario passes`(): List<DynamicTest> =
        scenarios.map { (name, scenario) ->
            DynamicTest.dynamicTest(name) {
                JdbcDb.inMemory().use { db ->
                    seed(db, scenario.obj("seed"))
                    val setsBefore = count(db, "SELECT COUNT(*) AS n FROM sets")
                    val notesBefore = count(db, "SELECT COUNT(*) AS n FROM coach_notes")

                    val script = ScriptedModel(scenario["script"]!!.jsonArray)
                    val answer = Coach(db, apiKey = "test-key", transport = script)
                        .ask(scenario.string("question"))

                    val outcome = Outcome(
                        answer = answer,
                        setsAdded = count(db, "SELECT COUNT(*) AS n FROM sets") - setsBefore,
                        notesAdded = db.select(
                            "SELECT content FROM coach_notes ORDER BY id LIMIT -1 OFFSET ?",
                            listOf(notesBefore),
                        ) { it.string("content") },
                    )
                    val failed = score(scenario.obj("expect"), outcome).filterValues { !it }.keys
                    assertTrue(failed.isEmpty(), "$name: $failed\nanswer: ${answer.text}")
                    assertFalse(answer.retried, "$name: the harness sent the scripted answer back")
                }
            }
        }

    // ----------------------------------------------------------------------

    private class Outcome(val answer: Answer, val setsAdded: Int, val notesAdded: List<String>)

    /** The same checks as evals.score in Python, as label to pass/fail. */
    private fun score(expect: JsonObject, outcome: Outcome): Map<String, Boolean> {
        val checks = linkedMapOf<String, Boolean>()
        val tools = outcome.answer.toolCalls.map { it.name }
        val text = outcome.answer.text

        expect.list("calls").forEach { entry ->
            val options = alternatives(entry)
            checks["called ${options.joinToString(" or ")}"] = options.any { it in tools }
        }
        expect.list("avoids").forEach { entry ->
            val tool = entry.jsonPrimitive.content
            checks["did not call $tool"] = tool !in tools
        }
        expect.list("quotes").forEach { entry ->
            val figure = entry.jsonPrimitive.content
            checks["quoted $figure"] = quotes(text, figure)
        }
        if (expect["grounded"]?.jsonPrimitive?.content == "true") {
            checks["every figure found in the data"] = outcome.answer.grounding.ok
        }
        expect.list("says").forEach { entry ->
            val options = alternatives(entry)
            checks["says ${options.joinToString(" / ")}"] =
                options.any { text.lowercase().contains(it.lowercase()) }
        }
        expect["sets_added"]?.let {
            checks["logged ${it.jsonPrimitive.content} sets"] =
                outcome.setsAdded == it.jsonPrimitive.content.toInt()
        }
        expect["remembers"]?.let {
            val word = it.jsonPrimitive.content.lowercase()
            checks["remembered a note mentioning $word"] =
                outcome.notesAdded.any { note -> note.lowercase().contains(word) }
        }
        return checks
    }

    /** Whether the answer states the figure, by the grounding check's own rules. */
    private fun quotes(answer: String, figure: String): Boolean {
        val baseline = GroundingCheck.check(answer, emptyList()).verified.toSet()
        return (GroundingCheck.check(answer, listOf(figure)).verified.toSet() - baseline).isNotEmpty()
    }

    private fun alternatives(entry: JsonElement): List<String> =
        if (entry is JsonArray) entry.map { it.jsonPrimitive.content } else listOf(entry.jsonPrimitive.content)

    // ----------------------------------------------------------------------

    private fun seed(db: Db, seed: JsonObject) {
        val exercises = seed["exercises"]?.jsonArray
        if (exercises == null) {
            db.seedExercises()
        } else {
            exercises.forEachIndexed { index, element ->
                val spec = element.jsonObject
                db.execute(
                    "INSERT INTO exercises (id, name, category, modality) VALUES (?, ?, ?, 'weight_reps')",
                    listOf(index + 1, spec.string("name"), spec["category"]?.jsonPrimitive?.content),
                )
                spec.list("muscles").forEach {
                    db.execute(
                        "INSERT INTO exercise_muscles (exercise_id, muscle, is_primary) VALUES (?, ?, 1)",
                        listOf(index + 1, it.jsonPrimitive.content),
                    )
                }
            }
        }
        seed.list("workouts").forEach { element ->
            val spec = element.jsonObject
            val sets = spec["sets"]!!.jsonArray.map { set ->
                val parts = set.jsonArray.map { it.jsonPrimitive }
                SetSpec(
                    exercise = parts[0].content,
                    weightKg = parts[1].content.toDoubleOrNull(),
                    reps = parts[2].content.toIntOrNull(),
                    warmup = parts.getOrNull(3)?.content == "true",
                )
            }
            db.addWorkout(TODAY.plusDays(spec.int("day").toLong()), sets)
        }
        seed.list("daily_metrics").forEach { element ->
            val spec = element.jsonObject
            db.addDailyMetric(
                TODAY.plusDays(spec.int("day").toLong()),
                spec.string("metric"),
                spec["source"]?.jsonPrimitive?.content ?: "gadgetbridge",
                spec["value"]!!.jsonPrimitive.content.toDouble(),
                spec.string("unit"),
            )
        }
        seed.list("notes").forEach { element ->
            val spec = element.jsonObject
            db.execute(
                "INSERT INTO coach_notes (kind, content) VALUES (?, ?)",
                listOf(spec.string("kind"), spec.string("content")),
            )
        }
    }

    private fun count(db: Db, sql: String): Int = db.selectOne(sql) { it.int("n") } ?: 0

    /**
     * Plays the scenario's `script` as Gemini responses: `text`, one `call`
     * with `args`, or several `calls`. Past the end the last step repeats.
     */
    private class ScriptedModel(private val steps: JsonArray) : Transport {
        private var requests = 0

        override fun post(url: String, body: String): String {
            val step = steps[minOf(requests, steps.size - 1)].jsonObject
            requests++
            val parts = buildJsonArray {
                if ("text" in step) {
                    add(buildJsonObject { put("text", step.string("text")) })
                } else {
                    val calls = step["calls"]?.jsonArray?.map { it.jsonObject }
                        ?: listOf(buildJsonObject {
                            put("name", step.string("call"))
                            put("args", step["args"] ?: JsonObject(emptyMap()))
                        })
                    calls.forEach { call ->
                        add(buildJsonObject {
                            put("functionCall", buildJsonObject {
                                put("name", call.string("name"))
                                put("args", call["args"] ?: JsonObject(emptyMap()))
                            })
                        })
                    }
                }
            }
            return buildJsonObject {
                put("candidates", buildJsonArray {
                    add(buildJsonObject {
                        put("content", buildJsonObject {
                            put("role", "model")
                            put("parts", parts)
                        })
                    })
                })
            }.toString()
        }
    }

    companion object {
        private val RELATIVE_DATE = Regex("""\{today(?:([+-])([0-9]+))?\}""")

        /** {today}, {today-7}, {today+1}, as in evals.resolve_dates. */
        fun resolveDates(text: String, today: LocalDate): String =
            RELATIVE_DATE.replace(text) { match ->
                val days = match.groupValues[2].ifEmpty { "0" }.toLong()
                (if (match.groupValues[1] == "-") today.minusDays(days) else today.plusDays(days)).toString()
            }

        private fun JsonObject.string(key: String) = this[key]!!.jsonPrimitive.content
        private fun JsonObject.int(key: String) = this[key]!!.jsonPrimitive.content.toInt()
        private fun JsonObject.obj(key: String) = this[key]?.jsonObject ?: JsonObject(emptyMap())
        private fun JsonObject.list(key: String): List<JsonElement> = this[key]?.jsonArray ?: emptyList()
    }
}
