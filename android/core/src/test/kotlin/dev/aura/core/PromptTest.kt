package dev.aura.core

import dev.aura.core.agent.Coach
import dev.aura.core.agent.Prompt
import dev.aura.core.agent.Transport
import java.io.File
import java.time.LocalDate
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Test

/**
 * The prompt, held to what the Python coach sends.
 *
 * Until this existed the two coaches were briefed differently, and the Android
 * one was told neither the date nor anything the athlete had asked it to
 * remember.
 */
class PromptTest {

    private val fixtures = File(System.getProperty("aura.fixtures") ?: "../fixtures")

    @Test
    fun `assembly matches the Python coach for every shared case`() {
        val document = Json.parseToJsonElement(fixtures.resolve("prompt_assembly.json").readText())
        val cases = document.jsonObject["cases"]!!.jsonArray
        assertTrue(cases.isNotEmpty())

        for (case in cases) {
            val c = case.jsonObject
            val notes =
                c["notes"]!!.jsonArray.map {
                    val pair = it.jsonArray
                    pair[0].jsonPrimitive.content to pair[1].jsonPrimitive.content
                }
            val built =
                Prompt.build(
                    c["instructions"]!!.jsonPrimitive.content,
                    LocalDate.parse(c["today"]!!.jsonPrimitive.content),
                    notes,
                )
            assertEquals(
                c["expected"]!!.jsonPrimitive.content,
                built,
                "case '${c["name"]!!.jsonPrimitive.content}' differs from Python",
            )
        }
    }

    @Test
    fun `the packaged instructions are the generated ones`() {
        val text = Prompt.instructions()
        assertTrue(text.startsWith("You are the athlete's personal strength and conditioning coach"))
        assertTrue("remember" in text, "the instruction to use remember is missing")
    }

    @Test
    fun `remembered facts are listed in a stable order`() {
        JdbcDb.inMemory().use { db ->
            db.execute("INSERT INTO coach_notes (kind, content) VALUES ('injury', 'Left shoulder')")
            db.execute("INSERT INTO coach_notes (kind, content) VALUES ('goal', 'Squat 140')")
            db.execute("INSERT INTO coach_notes (kind, content) VALUES ('goal', 'Run 10k')")
            db.execute(
                "INSERT INTO coach_notes (kind, content, is_active) VALUES ('goal', 'Old goal', 0)"
            )
            assertEquals(
                listOf("goal" to "Squat 140", "goal" to "Run 10k", "injury" to "Left shoulder"),
                Prompt.standingFacts(db),
                "by kind, then by the order they were recorded; inactive ones left out",
            )
        }
    }

    @Test
    fun `the coach actually sends the date and what it was told to remember`() {
        JdbcDb.inMemory().use { db ->
            db.execute(
                "INSERT INTO coach_notes (kind, content) VALUES ('injury', 'Left shoulder, no pressing')"
            )
            var sent = ""
            val transport = Transport { _, body ->
                sent = body
                """{"candidates":[{"content":{"role":"model","parts":[{"text":"Noted."}]}}]}"""
            }
            Coach(
                db,
                apiKey = "test-key",
                transport = transport,
                today = { LocalDate.of(2026, 9, 23) },
            ).ask("What should I train today?")

            assertTrue("Today is 2026-09-23." in sent, "the model was not told the date")
            assertTrue(
                "(injury) Left shoulder, no pressing" in sent,
                "a remembered injury never reached the model",
            )
        }
    }
}
