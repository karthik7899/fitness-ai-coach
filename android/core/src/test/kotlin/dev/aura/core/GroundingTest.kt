package dev.aura.core

import dev.aura.core.agent.GroundingCheck
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Test

/** The grounding check, held to the Python reference's verdicts. */
class GroundingTest {

    private val fixtures = File(System.getProperty("aura.fixtures") ?: "../fixtures")

    @Test
    fun `every shared case reaches the same verdict as Python`() {
        val cases =
            Json.parseToJsonElement(fixtures.resolve("grounding.json").readText())
                .jsonObject["cases"]!!.jsonArray
        assertTrue(cases.size >= 20, "the shared cases went missing")

        val disagreements =
            cases.mapNotNull { case ->
                val c = case.jsonObject
                fun strings(key: String) = c[key]!!.jsonArray.map { it.jsonPrimitive.content }
                val result = GroundingCheck.check(c["answer"]!!.jsonPrimitive.content, strings("sources"))
                val name = c["name"]!!.jsonPrimitive.content
                if (result.verified == strings("verified") && result.unverified == strings("unverified")) {
                    null
                } else {
                    "$name: Kotlin verified=${result.verified} unverified=${result.unverified}, " +
                        "Python verified=${strings("verified")} unverified=${strings("unverified")}"
                }
            }
        assertEquals(emptyList(), disagreements)
    }
}
