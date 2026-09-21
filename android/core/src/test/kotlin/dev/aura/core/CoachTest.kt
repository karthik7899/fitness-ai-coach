package dev.aura.core

import dev.aura.core.agent.Coach
import dev.aura.core.agent.CoachError
import dev.aura.core.agent.Tools
import dev.aura.core.agent.Transport
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue
import org.junit.jupiter.api.Test

/**
 * The coaching loop, with the network replaced by canned responses.
 *
 * The live call to Google cannot be tested without a key, so everything around
 * it is: which tools exist, that they run, that a function call is executed and
 * its result handed back, and that failures come out as something a person can
 * read.
 */
class CoachTest {

    private val json = Json

    /** Replays a fixed list of responses, and records what it was sent. */
    private class Replay(private vararg val responses: String) : Transport {
        val sent = mutableListOf<String>()
        private var index = 0

        override fun post(url: String, body: String): String {
            sent += body
            return responses[index++.coerceAtMost(responses.size - 1)]
        }
    }

    private fun textResponse(text: String) =
        """{"candidates":[{"content":{"role":"model","parts":[{"text":${json.encodeToString(
            kotlinx.serialization.json.JsonPrimitive.serializer(),
            kotlinx.serialization.json.JsonPrimitive(text),
        )}}]}}]}"""

    private fun callResponse(name: String, args: String) =
        """{"candidates":[{"content":{"role":"model","parts":[
           {"functionCall":{"name":"$name","args":$args}}]}}]}"""

    private fun withDb(block: (Db) -> Unit) =
        JdbcDb.inMemory().use { db ->
            db.seedExercises()
            db.addWorkout(TODAY, listOf(SetSpec("Back Squat", 100.0, 5)))
            block(db)
        }

    // ----------------------------------------------------------------------
    // The tool surface
    // ----------------------------------------------------------------------

    @Test
    fun `there is a handler for every generated declaration`() {
        // The declarations come from the Python app. If one is added there and
        // not implemented here, the phone's coach would call a tool that does
        // not exist — so this failing is the point.
        withDb { db ->
            for (name in Tools.names()) {
                val result =
                    runCatching { Tools.call(db, name, emptyArgs(name)) }.getOrElse { failure ->
                        throw AssertionError("No working handler for '$name': ${failure.message}")
                    }
                assertTrue(result.isNotEmpty(), "'$name' returned nothing at all")
            }
        }
    }

    /** Minimal valid arguments for each declared tool. */
    private fun emptyArgs(name: String): JsonObject {
        val today = TODAY.toString()
        val raw =
            when (name) {
                "get_daily_metrics", "get_training_load", "get_volume_summary" ->
                    """{"start_date":"$today","end_date":"$today"}"""
                "get_exercise_history" -> """{"exercise":"Back Squat"}"""
                "get_recent_activities" -> """{}"""
                "get_workout" -> """{"performed_on":"$today"}"""
                "list_exercises" -> """{}"""
                "log_set" -> """{"exercise":"Back Squat","reps":5,"weight_kg":100}"""
                "remember" -> """{"kind":"goal","content":"Squat 140kg"}"""
                else -> throw AssertionError("New tool '$name' has no arguments in this test")
            }
        return json.parseToJsonElement(raw).jsonObject
    }

    @Test
    fun `a tool reads real numbers out of the views`() {
        withDb { db ->
            val result =
                Tools.call(
                    db,
                    "get_volume_summary",
                    json.parseToJsonElement(
                        """{"start_date":"${TODAY.minusDays(7)}","end_date":"$TODAY",
                            "group_by":"day"}"""
                    ).jsonObject,
                )
            assertTrue(result["rows"].toString().contains("500"), "expected 500kg: $result")
        }
    }

    @Test
    fun `an unknown exercise suggests near matches instead of failing`() {
        withDb { db ->
            val result =
                Tools.call(
                    db,
                    "get_exercise_history",
                    json.parseToJsonElement("""{"exercise":"Squat"}""").jsonObject,
                )
            assertTrue(result.containsKey("error"))
            assertTrue(result["did_you_mean"].toString().contains("Back Squat"))
        }
    }

    // ----------------------------------------------------------------------
    // The loop
    // ----------------------------------------------------------------------

    @Test
    fun `a plain answer comes straight back`() {
        withDb { db ->
            val coach = Coach(db, apiKey = "test-key", transport = Replay(textResponse("Rest up.")))
            assertEquals("Rest up.", coach.ask("How am I doing?").text)
        }
    }

    @Test
    fun `a function call is executed and its result handed back`() {
        withDb { db ->
            val replay =
                Replay(
                    callResponse("get_volume_summary", """{"start_date":"$TODAY",
                        "end_date":"$TODAY","group_by":"day"}"""),
                    textResponse("You lifted 500kg today."),
                )
            val coach = Coach(db, apiKey = "test-key", transport = replay)
            val answer = coach.ask("What did I lift?")

            assertEquals("You lifted 500kg today.", answer.text)
            assertEquals(listOf("get_volume_summary"), answer.toolCalls.map { it.name })
            // The tool's real output must reach the model, not a placeholder.
            assertTrue(
                replay.sent.last().contains("functionResponse"),
                "the result was never sent back",
            )
            assertTrue(replay.sent.last().contains("500"), "the real numbers were not sent back")
        }
    }

    @Test
    fun `a failing tool is reported to the model rather than thrown`() {
        withDb { db ->
            val replay =
                Replay(
                    callResponse("get_workout", """{}"""), // missing performed_on
                    textResponse("I could not read that day."),
                )
            val coach = Coach(db, apiKey = "test-key", transport = replay)
            val answer = coach.ask("What did I do?")

            assertEquals("I could not read that day.", answer.text)
            assertTrue(answer.toolCalls.single().result.containsKey("error"))
            assertTrue(replay.sent.last().contains("error"))
        }
    }

    @Test
    fun `the tools are declared to the model on every request`() {
        withDb { db ->
            val replay = Replay(textResponse("Fine."))
            Coach(db, apiKey = "test-key", transport = replay).ask("Hello")
            val body = replay.sent.single()
            assertTrue(body.contains("functionDeclarations"))
            assertTrue(body.contains("get_training_load"))
        }
    }

    @Test
    fun `history is carried forward so the next turn has context`() {
        withDb { db ->
            val coach = Coach(db, apiKey = "test-key", transport = Replay(textResponse("Hi.")))
            val first = coach.ask("Hello")
            assertEquals(2, first.history.size) // the question and the answer

            val replay = Replay(textResponse("Still here."))
            Coach(db, apiKey = "test-key", transport = replay).ask("And?", first.history)
            assertTrue(replay.sent.single().contains("Hello"), "the earlier turn was dropped")
        }
    }

    @Test
    fun `a missing key says so before any request is made`() {
        withDb { db ->
            val replay = Replay(textResponse("unreachable"))
            val problem =
                assertFailsWith<CoachError> { Coach(db, apiKey = "", transport = replay).ask("Hi") }
            assertTrue(problem.message!!.contains("Settings"))
            assertTrue(replay.sent.isEmpty(), "a request was made without a key")
        }
    }

    @Test
    fun `a rejected key is explained in plain words`() {
        withDb { db ->
            val replay =
                Replay("""{"error":{"code":400,"message":"API key not valid. Please pass a valid API key."}}""")
            val problem =
                assertFailsWith<CoachError> {
                    Coach(db, apiKey = "bad", transport = replay).ask("Hi")
                }
            assertTrue(
                problem.message!!.contains("rejected by Google"),
                "unhelpful message: ${problem.message}",
            )
        }
    }

    @Test
    fun `a model that only ever calls tools is stopped`() {
        withDb { db ->
            // Always asks for another tool call, never answers.
            val replay =
                Replay(callResponse("list_exercises", "{}"))
            val problem =
                assertFailsWith<CoachError> {
                    Coach(db, apiKey = "test-key", transport = replay, maxRounds = 3).ask("Hi")
                }
            assertTrue(problem.message!!.contains("narrower"))
            assertEquals(3, replay.sent.size, "the round limit was not honoured")
        }
    }
}
