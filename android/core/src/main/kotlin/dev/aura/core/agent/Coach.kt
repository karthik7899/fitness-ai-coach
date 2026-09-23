package dev.aura.core.agent

import dev.aura.core.Db
import java.io.BufferedReader
import java.net.HttpURLConnection
import java.net.URL
import java.time.LocalDate
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

/**
 * The conversation so far, carried between turns.
 *
 * Opaque on purpose. What is inside is Gemini's wire format, and a screen that
 * had to know about that would break the moment the provider changed — so it
 * holds one of these and hands it back, and nothing above this module needs a
 * JSON library on its classpath to do it.
 */
class Conversation internal constructor(internal val contents: List<JsonObject>) {
    val isEmpty: Boolean
        get() = contents.isEmpty()

    /** How many turns have been exchanged, counting both sides. */
    val turns: Int
        get() = contents.size

    companion object {
        val EMPTY: Conversation = Conversation(emptyList())
    }
}

/**
 * The end of one exchange: what to show, the conversation to carry forward,
 * whether its figures checked out, and how it was arrived at.
 */
data class Answer(
    val text: String,
    val toolCalls: List<ToolCall>,
    val conversation: Conversation,
    val grounding: Grounding = Grounding.NOTHING_TO_CHECK,
    val trace: Trace = Trace.EMPTY,
    /** Whether the first answer quoted figures nothing returned, and was sent back. */
    val retried: Boolean = false,
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
    private val maxRounds: Int = 12,
    private val today: () -> LocalDate = { LocalDate.now() },
    private val clock: () -> Long = { System.nanoTime() },
) {

    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }

    private fun millisSince(start: Long): Long = (clock() - start) / 1_000_000

    fun ask(message: String, conversation: Conversation = Conversation.EMPTY): Answer {
        if (apiKey.isBlank()) {
            throw CoachError("No Gemini API key set. Add one in Settings.")
        }

        val started = clock()
        val contents = conversation.contents.toMutableList()
        contents += userContent(message)
        val calls = mutableListOf<ToolCall>()
        val steps = mutableListOf<TraceStep>()
        var usage = Usage()
        var retried = false

        repeat(maxRounds) {
            val callStarted = clock()
            val response = json.parseToJsonElement(send(contents)).jsonObject
            rejectError(response)
            val spent = usageOf(response)
            usage += spent
            steps +=
                TraceStep(
                    TraceStep.Kind.MODEL,
                    model,
                    if (spent.totalTokens > 0) "${spent.totalTokens} tokens" else "",
                    millisSince(callStarted),
                )

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

                val checkStarted = clock()
                val grounding = GroundingCheck.check(text, sourcesIn(contents))
                steps +=
                    TraceStep(
                        TraceStep.Kind.CHECK,
                        "grounding",
                        describe(grounding),
                        millisSince(checkStarted),
                        failed = !grounding.ok,
                    )

                // One chance to correct itself. More would let a model that
                // cannot find a figure burn the round budget looking for it.
                if (!grounding.ok && !retried) {
                    retried = true
                    steps +=
                        TraceStep(
                            TraceStep.Kind.RETRY,
                            "sent back",
                            grounding.unverified.joinToString(", "),
                            0,
                        )
                    contents += userContent(correction(grounding))
                    return@repeat
                }

                return Answer(
                    text = text,
                    toolCalls = calls,
                    conversation = Conversation(contents.toList()),
                    grounding = grounding,
                    trace = Trace(steps.toList(), usage, millisSince(started)),
                    retried = retried,
                )
            }

            val results = buildJsonArray {
                for (call in requested) {
                    val name = call["name"]!!.jsonPrimitive.content
                    val arguments = call["args"]?.jsonObject ?: JsonObject(emptyMap())
                    val toolStarted = clock()
                    val result = runTool(name, arguments)
                    steps +=
                        TraceStep(
                            TraceStep.Kind.TOOL,
                            name,
                            summarise(arguments),
                            millisSince(toolStarted),
                            failed = result.containsKey("error"),
                        )
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
     * What the model's figures may legitimately come from: what the tools
     * returned and what the athlete said, anywhere in this conversation.
     *
     * Not the model's own earlier words — they are not evidence. And not the
     * corrections this harness sends: they quote the unverified figures back,
     * and counting them would let a retry verify itself by repetition.
     */
    private fun sourcesIn(contents: List<JsonObject>): List<String> =
        contents
            .filter { it["role"]?.jsonPrimitive?.content == "user" }
            .flatMap { content ->
                content["parts"]?.jsonArray.orEmpty().mapNotNull { part ->
                    val obj = part.jsonObject
                    val text = obj["text"]?.jsonPrimitive?.content
                    when {
                        text != null && !text.startsWith(CORRECTION_PREFIX) -> text
                        obj["functionResponse"] != null -> obj["functionResponse"].toString()
                        else -> null
                    }
                }
            }

    private fun correction(grounding: Grounding): String =
        CORRECTION_PREFIX + CORRECTION_BODY.replace("{figures}", grounding.unverified.joinToString(", "))

    private fun describe(grounding: Grounding): String {
        val total = grounding.verified.size + grounding.unverified.size
        return when {
            total == 0 -> "no figures to check"
            grounding.ok -> "$total of $total traced"
            else ->
                "${grounding.unverified.size} of $total not found: " +
                    grounding.unverified.joinToString(", ")
        }
    }

    private fun summarise(arguments: JsonObject): String =
        arguments.entries.joinToString(", ") { (key, value) ->
            val shown = (value as? JsonPrimitive)?.content ?: value.toString()
            "$key=$shown"
        }

    private fun usageOf(response: JsonObject): Usage {
        val meta = response["usageMetadata"]?.jsonObject ?: return Usage()
        fun count(key: String) = meta[key]?.jsonPrimitive?.content?.toIntOrNull() ?: 0
        return Usage(
            count("promptTokenCount"),
            count("candidatesTokenCount"),
            count("totalTokenCount"),
        )
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
                putJsonArray("parts") {
                    add(buildJsonObject { put("text", Prompt.forToday(db, today())) })
                }
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

        /**
         * What the harness says when an answer's figures do not check out —
         * exported from the Python coach, because a retry worded differently
         * is a different retry. The prefix marks it so it is never mistaken
         * for evidence.
         */
        private val correctionText: JsonObject by lazy {
            val text =
                Coach::class.java.getResourceAsStream("/aura/correction.json")
                    ?.bufferedReader()
                    ?.use { it.readText() }
                    ?: error("/aura/correction.json is missing. Run scripts/export_tools.py.")
            Json.parseToJsonElement(text).jsonObject
        }

        val CORRECTION_PREFIX: String by lazy { correctionText["prefix"]!!.jsonPrimitive.content }
        private val CORRECTION_BODY: String by lazy { correctionText["body"]!!.jsonPrimitive.content }

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
