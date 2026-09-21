package dev.aura.core.agent

import dev.aura.core.Db
import java.io.BufferedReader
import java.net.HttpURLConnection
import java.net.URL
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.putJsonObject

/** What the model asked for, and what it was told. */
data class ToolCall(val name: String, val arguments: JsonObject, val result: JsonObject)

/** The end of one exchange: what to show, and the history to carry forward. */
data class Answer(
    val text: String,
    val toolCalls: List<ToolCall>,
    val history: List<JsonObject>,
)

/** Anything that can POST JSON and return JSON. Injected so the loop is testable. */
fun interface Transport {
    fun post(url: String, body: String): String
}

class CoachError(message: String) : RuntimeException(message)

/**
 * The coaching loop.
 *
 * Gemini answers either with text or with a request to call one of the tools.
 * This runs that exchange until it produces text: call the tools it asked for,
 * hand back the results, ask again. The model is never given the database —
 * only what the tools return — so every figure it quotes traces to a view.
 *
 * The transport is injected because the network call is the one part that
 * cannot be tested without a key; everything around it can be, and is.
 */
class Coach(
    private val db: Db,
    private val apiKey: String,
    private val model: String = DEFAULT_MODEL,
    private val transport: Transport = HttpTransport(),
    private val maxRounds: Int = 8,
) {

    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }

    fun ask(message: String, history: List<JsonObject> = emptyList()): Answer {
        if (apiKey.isBlank()) {
            throw CoachError("No Gemini API key set. Add one in Settings.")
        }

        val contents = history.toMutableList()
        contents += userContent(message)
        val calls = mutableListOf<ToolCall>()

        repeat(maxRounds) {
            val response = json.parseToJsonElement(send(contents)).jsonObject
            rejectError(response)

            val parts = firstCandidateParts(response)
            if (parts.isEmpty()) {
                throw CoachError("The model returned nothing. Try rephrasing.")
            }

            // Keep the model's own turn verbatim, including any thought
            // signatures: dropping them breaks multi-step tool use.
            contents += buildJsonObject {
                put("role", "model")
                put("parts", JsonArray(parts))
            }

            val requested = parts.mapNotNull { it.jsonObject["functionCall"]?.jsonObject }
            if (requested.isEmpty()) {
                val text =
                    parts.mapNotNull { it.jsonObject["text"]?.jsonPrimitive?.content }
                        .joinToString("")
                return Answer(text = text, toolCalls = calls, history = contents)
            }

            val results = buildJsonArray {
                for (call in requested) {
                    val name = call["name"]!!.jsonPrimitive.content
                    val arguments = call["args"]?.jsonObject ?: JsonObject(emptyMap())
                    val result = runTool(name, arguments)
                    calls += ToolCall(name, arguments, result)
                    add(
                        buildJsonObject {
                            putJsonObject("functionResponse") {
                                put("name", name)
                                put("response", result)
                            }
                        }
                    )
                }
            }
            contents += buildJsonObject {
                put("role", "user")
                put("parts", results)
            }
        }

        throw CoachError("The coach kept calling tools without answering. Try a narrower question.")
    }

    /**
     * A failing tool is reported to the model rather than thrown.
     *
     * It chose the arguments, so it is the one that can correct them — and an
     * exception here would lose an otherwise good conversation.
     */
    private fun runTool(name: String, arguments: JsonObject): JsonObject =
        try {
            Tools.call(db, name, arguments)
        } catch (e: Exception) {
            buildJsonObject { put("error", e.message ?: e.toString()) }
        }

    private fun send(contents: List<JsonObject>): String {
        val body = buildJsonObject {
            put("contents", JsonArray(contents))
            putJsonArray("tools") {
                add(buildJsonObject { put("functionDeclarations", JsonArray(Tools.declarations())) })
            }
            putJsonObject("systemInstruction") {
                putJsonArray("parts") { add(buildJsonObject { put("text", SYSTEM_PROMPT) }) }
            }
        }
        return transport.post("$ENDPOINT/$model:generateContent?key=$apiKey", body.toString())
    }

    private fun rejectError(response: JsonObject) {
        val error = response["error"]?.jsonObject ?: return
        val message = error["message"]?.jsonPrimitive?.content ?: "Unknown error"
        throw CoachError(
            when {
                "API_KEY_INVALID" in message || "API key not valid" in message ->
                    "That key was rejected by Google. Check it was copied in full."
                "quota" in message.lowercase() ->
                    "Google says the key is out of quota for now."
                else -> message
            }
        )
    }

    private fun firstCandidateParts(response: JsonObject): List<JsonObject> =
        response["candidates"]
            ?.jsonArray
            ?.firstOrNull()
            ?.jsonObject
            ?.get("content")
            ?.jsonObject
            ?.get("parts")
            ?.jsonArray
            ?.map { it.jsonObject }
            .orEmpty()

    private fun userContent(message: String): JsonObject = buildJsonObject {
        put("role", "user")
        putJsonArray("parts") { add(buildJsonObject { put("text", message) }) }
    }

    companion object {
        const val ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
        const val DEFAULT_MODEL = "gemini-3.8-flash"

        val SYSTEM_PROMPT =
            """
            You are a strength and conditioning coach with direct access to this
            athlete's training database. Call the tools for every number you
            quote — never estimate, never compute in your head, and never invent
            a figure the tools did not return. If the data does not answer the
            question, say so. Weights are kilograms, distances metres, durations
            seconds. Be concise and specific.
            """
                .trimIndent()
    }
}

/** The real network call. Everything above it is testable without one. */
class HttpTransport(private val timeoutMs: Int = 60_000) : Transport {
    override fun post(url: String, body: String): String {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.requestMethod = "POST"
        connection.doOutput = true
        connection.connectTimeout = timeoutMs
        connection.readTimeout = timeoutMs
        connection.setRequestProperty("Content-Type", "application/json")
        return try {
            connection.outputStream.use { it.write(body.toByteArray()) }
            // Google puts the useful part of a failure in the error stream, so
            // read whichever one is there and let the caller interpret it.
            val stream = if (connection.responseCode in 200..299) {
                connection.inputStream
            } else {
                connection.errorStream ?: connection.inputStream
            }
            stream.bufferedReader().use(BufferedReader::readText)
        } finally {
            connection.disconnect()
        }
    }
}
