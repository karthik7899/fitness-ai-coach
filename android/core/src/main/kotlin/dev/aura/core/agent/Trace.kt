package dev.aura.core.agent

/**
 * What happened while an answer was being produced.
 *
 * Kept because "why did it say that?" deserves an answer better than a shrug:
 * which tools ran, with what arguments, how long each took, what the model
 * spent, and whether its figures checked out.
 */
data class TraceStep(
    val kind: Kind,
    val label: String,
    val detail: String,
    val millis: Long,
    val failed: Boolean = false,
) {
    enum class Kind { MODEL, TOOL, CHECK, RETRY }
}

data class Usage(val promptTokens: Int = 0, val outputTokens: Int = 0, val totalTokens: Int = 0) {
    operator fun plus(other: Usage) =
        Usage(
            promptTokens + other.promptTokens,
            outputTokens + other.outputTokens,
            totalTokens + other.totalTokens,
        )
}

data class Trace(val steps: List<TraceStep>, val usage: Usage, val totalMillis: Long) {
    val modelCalls: Int
        get() = steps.count { it.kind == TraceStep.Kind.MODEL }

    val toolCalls: Int
        get() = steps.count { it.kind == TraceStep.Kind.TOOL }

    companion object {
        val EMPTY = Trace(emptyList(), Usage(), 0)
    }
}
