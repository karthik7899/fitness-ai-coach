package dev.aura.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

/**
 * Settings the user enters, kept in the database rather than a file.
 *
 * `app_settings` is the same table the desktop app writes, so a restored backup
 * carries the key and the watch folders with it. The key never leaves this
 * layer in full — [maskedApiKey] is what the UI is given, because a screen that
 * prints a credential is a screen someone will eventually screenshot.
 */
object Settings {

    const val GEMINI = "gemini"
    const val INGEST = "ingest"

    private val json = Json

    fun read(db: Db, key: String): JsonObject? =
        db.selectOne("SELECT value FROM app_settings WHERE \"key\" = ?", listOf(key)) {
            it.stringOrNull("value")
        }
            ?.let { json.parseToJsonElement(it).jsonObject }

    fun write(db: Db, key: String, value: JsonObject) {
        db.execute(
            """
            INSERT INTO app_settings ("key", value) VALUES (?, ?)
            ON CONFLICT ("key") DO UPDATE SET value = excluded.value
            """,
            listOf(key, value.toString()),
        )
    }

    fun clear(db: Db, key: String) {
        db.execute("DELETE FROM app_settings WHERE \"key\" = ?", listOf(key))
    }

    // ----------------------------------------------------------------------

    fun apiKey(db: Db): String? =
        read(db, GEMINI)?.get("api_key")?.jsonPrimitive?.content?.ifBlank { null }

    fun model(db: Db): String =
        read(db, GEMINI)?.get("model")?.jsonPrimitive?.content?.ifBlank { null }
            ?: DEFAULT_MODEL

    fun saveGemini(db: Db, apiKey: String?, model: String?) {
        val existing = read(db, GEMINI)
        write(
            db,
            GEMINI,
            buildJsonObject {
                val key = apiKey?.trim()?.ifBlank { null }
                    ?: existing?.get("api_key")?.jsonPrimitive?.content
                val chosen = model?.trim()?.ifBlank { null }
                    ?: existing?.get("model")?.jsonPrimitive?.content
                if (key != null) put("api_key", key)
                if (chosen != null) put("model", chosen)
            },
        )
    }

    fun clearApiKey(db: Db) {
        val model = read(db, GEMINI)?.get("model")?.jsonPrimitive?.content
        if (model == null) clear(db, GEMINI)
        else write(db, GEMINI, buildJsonObject { put("model", model) })
    }

    fun watchFolders(db: Db): List<String> =
        read(db, INGEST)?.get("watch_dirs")?.jsonArray?.map { it.jsonPrimitive.content }
            ?: emptyList()

    fun saveWatchFolders(db: Db, folders: List<String>) {
        val cleaned = folders.map { it.trim() }.filter { it.isNotEmpty() }
        write(
            db,
            INGEST,
            buildJsonObject {
                put(
                    "watch_dirs",
                    kotlinx.serialization.json.JsonArray(cleaned.map { JsonPrimitive(it) }),
                )
            },
        )
    }

    /** Enough to recognise which key is set, not enough to use it. */
    fun maskedApiKey(db: Db): String? = apiKey(db)?.let { mask(it) }

    fun mask(secret: String): String =
        if (secret.length <= 4) "…" else "…" + secret.takeLast(4)

    const val DEFAULT_MODEL = "gemini-3.8-flash"
}
