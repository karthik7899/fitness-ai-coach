package dev.aura.core.agent

import dev.aura.core.Db
import java.time.LocalDate

/**
 * What the coach is told before every question.
 *
 * The instructions are generated from the Python app — two apps phrasing the
 * brief differently are two different coaches, and an eval of one says nothing
 * about the other. The assembly follows the same rules on both sides, pinned by
 * `fixtures/prompt_assembly.json`.
 */
object Prompt {

    const val RESOURCE_PATH: String = "/aura/system_prompt.txt"

    /** The generated instructions, exactly as the Python coach sends them. */
    fun instructions(): String =
        Prompt::class.java.getResourceAsStream(RESOURCE_PATH)
            ?.bufferedReader()
            ?.use { it.readText() }
            ?: error(
                "$RESOURCE_PATH is missing from the classpath. " +
                    "Run scripts/export_tools.py to generate it."
            )

    /**
     * Instructions, then today's date, then what the athlete has told us.
     *
     * The date is what lets "this week" become a date range the tools can
     * query. The facts are what `remember` saves — without them here, telling
     * the coach about an injury stored it and then ignored it forever after.
     */
    fun build(instructions: String, today: LocalDate, notes: List<Pair<String, String>>): String {
        val context = mutableListOf(instructions, "\nToday is $today.")
        if (notes.isNotEmpty()) {
            context += "\nStanding facts about this athlete:"
            notes.forEach { (kind, content) -> context += "- ($kind) $content" }
        } else {
            context += "\nNo standing facts recorded for this athlete yet."
        }
        return context.joinToString("\n")
    }

    /** Active remembered facts, in the same order the Python coach lists them. */
    fun standingFacts(db: Db): List<Pair<String, String>> =
        db.select(
            "SELECT kind, content FROM coach_notes WHERE is_active ORDER BY kind, id"
        ) { it.string("kind") to it.string("content") }

    fun forToday(db: Db, today: LocalDate = LocalDate.now()): String =
        build(instructions(), today, standingFacts(db))
}
