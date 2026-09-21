package dev.aura.core.presentation

import java.time.LocalDate
import java.time.format.DateTimeFormatter
import kotlin.math.abs
import kotlin.math.roundToLong

/**
 * How numbers are written.
 *
 * In `core` rather than in the UI because it is the part with rules — trailing
 * zeros on a training number read as false precision, and thousands separators
 * matter more on a phone than anywhere else — and because rules can be tested.
 */
object Format {

    private val DAY = DateTimeFormatter.ofPattern("d MMM")
    private val DAY_WITH_YEAR = DateTimeFormatter.ofPattern("d MMM yyyy")

    /**
     * A plain number, with no more decimals than it needs.
     *
     * `102.50` claims a precision the scales do not have, and `100.00` is just
     * noise on a tile, so trailing zeros go — including all of them.
     */
    fun number(value: Double, decimals: Int = 2): String {
        val text = String.format("%.${decimals}f", value)
        val trimmed =
            if ('.' in text) text.trimEnd('0').trimEnd('.') else text
        val point = trimmed.indexOf('.')
        return if (point < 0) {
            group(trimmed.toLong())
        } else {
            group(trimmed.substring(0, point).toLong()) + trimmed.substring(point)
        }
    }

    fun kg(value: Double): String = "${number(value)} kg"

    /** Volume gets compact treatment: a dashboard tile is not the place for 10,872. */
    fun compactKg(value: Double): String =
        when {
            abs(value) >= 1_000_000 -> "${number(value / 1_000_000, 1)}M kg"
            abs(value) >= 10_000 -> "${number(value / 1_000, 1)}K kg"
            else -> kg(value)
        }

    fun ratio(value: Double?): String = value?.let { number(it, 2) } ?: "—"

    fun day(date: LocalDate, today: LocalDate = LocalDate.now()): String =
        when (date) {
            today -> "Today"
            today.minusDays(1) -> "Yesterday"
            else -> date.format(if (date.year == today.year) DAY else DAY_WITH_YEAR)
        }

    /** Underscored metric keys are storage, not writing. */
    fun metricName(metric: String): String =
        when (metric) {
            "resting_hr" -> "Resting HR"
            "hrv_ms" -> "HRV"
            "sleep_minutes" -> "Sleep"
            "body_weight_kg" -> "Body weight"
            "active_minutes" -> "Active minutes"
            else -> metric.replace('_', ' ').replaceFirstChar { it.uppercase() }
        }

    fun metricValue(metric: String, value: Double, unit: String?): String =
        when (metric) {
            // Minutes are how it is stored; hours are how it is read.
            "sleep_minutes" -> {
                val hours = (value / 60).toInt()
                val minutes = (value % 60).roundToLong()
                if (hours > 0) "${hours}h ${minutes}m" else "${minutes}m"
            }
            "steps" -> group(value.roundToLong())
            else -> listOfNotNull(number(value), unit?.ifBlank { null }).joinToString(" ")
        }

    private fun group(value: Long): String {
        val digits = abs(value).toString()
        val grouped = StringBuilder()
        for ((index, digit) in digits.withIndex()) {
            if (index > 0 && (digits.length - index) % 3 == 0) grouped.append(',')
            grouped.append(digit)
        }
        return if (value < 0) "-$grouped" else grouped.toString()
    }
}

/**
 * What an acute:chronic ratio means, as a label rather than a number.
 *
 * The bands are the ones the coach's own tool description uses, so the app and
 * the coach cannot describe the same number differently.
 */
enum class LoadBand(val label: String) {
    UNKNOWN("Not enough history"),
    DETRAINING("Backing off"),
    STEADY("Steady build"),
    STRETCHED("Pushing"),
    SPIKE("Spike");

    companion object {
        fun of(acwr: Double?): LoadBand =
            when {
                acwr == null -> UNKNOWN
                acwr < 0.8 -> DETRAINING
                acwr <= 1.3 -> STEADY
                acwr <= 1.5 -> STRETCHED
                else -> SPIKE
            }
    }
}
