package dev.aura.core

import dev.aura.core.agent.Coach
import dev.aura.core.agent.TraceStep.Kind
import dev.aura.core.agent.Transport
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import org.junit.jupiter.api.Test

/**
 * The harness around the coach: the grounding check, its one corrective retry,
 * and the trace. The model is scripted, so each test says exactly what the
 * model does and asserts what the harness does about it.
 */
class HarnessTest {

    private class Script(private vararg val responses: String) : Transport {
        val sent = mutableListOf<String>()
        override fun post(url: String, body: String): String {
            sent += body
            return responses[(sent.size - 1).coerceAtMost(responses.size - 1)]
        }
    }

    private fun text(answer: String, tokens: Int = 0) =
        """{"candidates":[{"content":{"role":"model","parts":[{"text":"$answer"}]}}]""" +
            (if (tokens > 0) ""","usageMetadata":{"promptTokenCount":${tokens - 10},""" +
                """"candidatesTokenCount":10,"totalTokenCount":$tokens}}""" else "}")

    private fun call(name: String, args: String, tokens: Int = 0) =
        """{"candidates":[{"content":{"role":"model","parts":[""" +
            """{"functionCall":{"name":"$name","args":$args}}]}}]""" +
            (if (tokens > 0) ""","usageMetadata":{"totalTokenCount":$tokens}}""" else "}")

    private val daily = """{"start_date":"$TODAY","end_date":"$TODAY","group_by":"day"}"""

    private fun withCoach(script: Script, block: (Coach) -> Unit) =
        JdbcDb.inMemory().use { db ->
            db.seedExercises()
            db.addWorkout(TODAY, listOf(SetSpec("Back Squat", 100.0, 5))) // 500 kg
            block(Coach(db, apiKey = "test-key", transport = script))
        }

    @Test
    fun `a grounded answer goes straight through`() {
        val script = Script(call("get_volume_summary", daily), text("You lifted 500 kg today."))
        withCoach(script) { coach ->
            val answer = coach.ask("What did I lift?")
            assertTrue(answer.grounding.ok)
            assertEquals(listOf("500"), answer.grounding.verified)
            assertFalse(answer.retried)
            assertEquals(2, script.sent.size, "no retry should have been made")
        }
    }

    @Test
    fun `an invented figure is sent back once, and the corrected answer kept`() {
        val script =
            Script(
                text("You lifted 12,000 kg."),
                call("get_volume_summary", daily),
                text("You lifted 500 kg today."),
            )
        withCoach(script) { coach ->
            val answer = coach.ask("What did I lift?")
            assertTrue(answer.retried)
            assertTrue(answer.grounding.ok, "the corrected answer should check out")
            assertEquals("You lifted 500 kg today.", answer.text)
            assertTrue(
                script.sent[1].contains("[Grounding check]") && script.sent[1].contains("12,000"),
                "the model was not told which figure to fix",
            )
        }
    }

    @Test
    fun `only one retry, and an answer that still fails is flagged rather than hidden`() {
        val script = Script(text("You lifted 12,000 kg."), text("It was 11,500 kg."))
        withCoach(script) { coach ->
            val answer = coach.ask("What did I lift?")
            assertTrue(answer.retried)
            assertEquals(listOf("11,500"), answer.grounding.unverified)
            assertEquals(2, script.sent.size, "a second retry was made")
        }
    }

    @Test
    fun `the correction cannot vouch for the figure it quotes`() {
        // The corrective message says "you quoted 12,000". If that counted as
        // a source, repeating the figure would make it verified.
        val script = Script(text("You averaged 12,000 steps."), text("You averaged 12,000 steps."))
        withCoach(script) { coach ->
            val answer = coach.ask("How many steps?")
            assertEquals(listOf("12,000"), answer.grounding.unverified)
        }
    }

    @Test
    fun `figures from the athlete's own question are grounded`() {
        val script = Script(text("Over the last 30 days nothing was logged."))
        withCoach(script) { coach ->
            val answer = coach.ask("How was the last 30 days?")
            assertTrue(answer.grounding.ok)
            assertFalse(answer.retried)
        }
    }

    @Test
    fun `the trace records each step in order`() {
        val script = Script(call("get_volume_summary", daily), text("You lifted 500 kg today."))
        withCoach(script) { coach ->
            val trace = coach.ask("What did I lift?").trace
            assertEquals(
                listOf(Kind.MODEL, Kind.TOOL, Kind.MODEL, Kind.CHECK),
                trace.steps.map { it.kind },
            )
            val tool = trace.steps.single { it.kind == Kind.TOOL }
            assertEquals("get_volume_summary", tool.label)
            assertTrue("group_by=day" in tool.detail, "the tool's arguments were not recorded")
            assertTrue(trace.steps.all { it.millis >= 0 })
            assertEquals(1, trace.toolCalls)
            assertEquals(2, trace.modelCalls)
        }
    }

    @Test
    fun `a retry shows in the trace`() {
        val script = Script(text("You lifted 12,000 kg."), text("Nothing logged yet."))
        withCoach(script) { coach ->
            val kinds = coach.ask("What did I lift?").trace.steps.map { it.kind }
            assertEquals(listOf(Kind.MODEL, Kind.CHECK, Kind.RETRY, Kind.MODEL, Kind.CHECK), kinds)
        }
    }

    @Test
    fun `a failing tool is marked in the trace`() {
        val script = Script(call("get_workout", "{}"), text("I could not read that day."))
        withCoach(script) { coach ->
            val tool = coach.ask("What did I do?").trace.steps.single { it.kind == Kind.TOOL }
            assertTrue(tool.failed)
        }
    }

    @Test
    fun `token use is summed across every model call`() {
        val script =
            Script(call("get_volume_summary", daily, tokens = 120), text("You lifted 500 kg.", tokens = 80))
        withCoach(script) { coach ->
            assertEquals(200, coach.ask("What did I lift?").trace.usage.totalTokens)
        }
    }
}
