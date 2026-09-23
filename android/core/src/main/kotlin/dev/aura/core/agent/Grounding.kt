package dev.aura.core.agent

import java.math.BigDecimal
import java.math.RoundingMode

/** Which of an answer's figures could be traced, and which could not. */
data class Grounding(val verified: List<String>, val unverified: List<String>) {
    val ok: Boolean
        get() = unverified.isEmpty()

    companion object {
        val NOTHING_TO_CHECK = Grounding(emptyList(), emptyList())
    }
}

/**
 * Checking that the coach's figures came from somewhere.
 *
 * A port of `api/app/agent/grounding.py`, which is the reference: the rules are
 * documented there, and `fixtures/grounding.json` holds the verdicts this must
 * reach on the same inputs. Change a rule in one and the other's build fails.
 *
 * The patterns spell out ASCII classes rather than using \d, \w, \s or \b. On
 * Android `java.util.regex` is ICU underneath, where those are Unicode-aware;
 * on the JVM that runs the tests they are not. Spelled out, the three engines —
 * ICU, the JVM, and Python — read them the same way.
 */
object GroundingCheck {

    /** Numbers the app defines: the acute and chronic load windows, in days. */
    private val DEFINITIONAL = listOf(7.0, 28.0)

    private val AS_WRITTEN = 1 to 1
    private val FROM_METRES = 1 to 1000
    private val FROM_KG = 1 to 1000
    private val FROM_MINUTES_TO_HOURS = 1 to 60
    private val FROM_SECONDS = 1 to 60
    private val FROM_HOURS = 60 to 1
    private val FROM_KM = 1000 to 1
    private val FROM_TONNES = 1000 to 1

    private val UNIT_RESCALINGS: Map<String, List<Pair<Int, Int>>> = buildMap {
        fun all(words: List<String>, scales: List<Pair<Int, Int>>) = words.forEach { put(it, scales) }
        all(listOf("km", "kms", "kilometre", "kilometres", "kilometer", "kilometers"), listOf(FROM_METRES))
        all(listOf("t", "tonne", "tonnes", "ton", "tons"), listOf(FROM_KG))
        all(listOf("h", "hr", "hrs", "hour", "hours"), listOf(FROM_MINUTES_TO_HOURS))
        all(listOf("min", "mins", "minute", "minutes"), listOf(FROM_SECONDS, FROM_HOURS))
        all(listOf("s", "sec", "secs", "second", "seconds"), listOf(60 to 1))
        all(listOf("metre", "metres", "meter", "meters"), listOf(FROM_KM))
        all(listOf("kg", "kgs", "kilo", "kilos", "kilogram", "kilograms"), listOf(FROM_TONNES))
        // Bare "m" is minutes or metres; both are allowed rather than guessed.
        put("m", listOf(FROM_SECONDS, FROM_KM))
    }

    private const val MONTH = """(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"""
    private val ISO_DATE =
        Regex("""(?<![A-Za-z0-9_])[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[T ][0-9:.]+Z?)?(?![A-Za-z0-9_])""")
    private val NAMED_DATE =
        Regex(
            """(?i)(?<![A-Za-z0-9_])[0-9]{1,2}(?:st|nd|rd|th)?[ \t]+""" + MONTH +
                """(?:[ \t]+[0-9]{4})?""" +
                """|(?<![A-Za-z0-9_])""" + MONTH +
                """[ \t]+[0-9]{1,2}(?:st|nd|rd|th)?(?:,?[ \t]+[0-9]{4})?"""
        )
    private val ONE_REP_MAX = Regex("""(?i)(?<![A-Za-z0-9_])e?1rm(?![A-Za-z0-9_])""")
    private val LIST_MARKER = Regex("""(?m)^[ \t]*[0-9]+[.)][ \t]""")
    private val HOURS_MINUTES = Regex("""(?<![A-Za-z0-9_])([0-9]+)h[ \t]*([0-9]+)m(?![A-Za-z0-9_])""")
    private const val NUMBER_BODY =
        """([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.([0-9]+))?((?:[Kk]|M)(?![A-Za-z])|%)?(?![0-9])"""
    /** In an answer, "4x5" is two figures, so only a digit or a point may precede one. */
    private val NUMBER = Regex("""(?<![0-9.])""" + NUMBER_BODY)
    /** In tool results a digit inside an identifier is part of a key, not a value. */
    private val SOURCE_NUMBER = Regex("""(?<![A-Za-z0-9_.])""" + NUMBER_BODY)
    private val UNIT = Regex("""[ \t]*([A-Za-z]+)""")

    private data class Claim(
        val text: String,
        val mantissa: BigDecimal,
        val decimals: Int,
        val suffix: String?,
        val unit: String?,
    )

    private fun stripCommon(text: String): String =
        ONE_REP_MAX.replace(ISO_DATE.replace(text, " "), " ")

    private fun claimsIn(answer: String): List<Claim> {
        var text = stripCommon(answer)
        text = NAMED_DATE.replace(text, " ")
        text = LIST_MARKER.replace(text, " ")

        val found = mutableListOf<Claim>()
        text =
            HOURS_MINUTES.replace(text) { match ->
                val minutes = match.groupValues[1].toInt() * 60 + match.groupValues[2].toInt()
                found += Claim(match.value, BigDecimal(minutes), 0, null, "min")
                " "
            }

        for (match in NUMBER.findAll(text)) {
            val whole = match.groupValues[1]
            val fraction = match.groups[2]?.value
            val suffix = match.groups[3]?.value
            val written = whole.replace(",", "") + (fraction?.let { ".$it" } ?: "")
            // Anchored at the end of the number, as Python's match(text, pos) is.
            val unit =
                UNIT.find(text, match.range.last + 1)
                    ?.takeIf { it.range.first == match.range.last + 1 }
                    ?.groupValues
                    ?.get(1)
                    ?.lowercase()
            found +=
                Claim(
                    text = match.value,
                    mantissa = BigDecimal(written),
                    decimals = fraction?.length ?: 0,
                    suffix = suffix,
                    unit = unit,
                )
        }

        val unique = LinkedHashMap<String, Claim>()
        for (claim in found) unique.putIfAbsent(claim.text, claim)
        return unique.values.toList()
    }

    private fun poolFrom(sources: List<String>): List<Double> {
        val values = DEFINITIONAL.toMutableList()
        for (source in sources) {
            for (match in SOURCE_NUMBER.findAll(stripCommon(source))) {
                val whole = match.groupValues[1]
                val fraction = match.groups[2]?.value
                values += (whole.replace(",", "") + (fraction?.let { ".$it" } ?: "")).toDouble()
            }
        }
        return values
    }

    private fun multipliers(suffix: String?): List<Double> =
        when (suffix) {
            "K", "k" -> listOf(1000.0)
            "M" -> listOf(1_000_000.0)
            "%" -> listOf(1.0, 0.01)
            else -> listOf(1.0)
        }

    private fun precision(claim: Claim): Int {
        // A big round number is an approximation; "10 reps" still means ten.
        if (claim.decimals == 0 && claim.suffix == null && claim.mantissa >= BigDecimal(1000)) {
            val digits = claim.mantissa.toBigInteger().toString()
            return -(digits.length - digits.trimEnd('0').length)
        }
        return claim.decimals
    }

    /** BigDecimal(double) is the exact binary value, as Python's Decimal(float) is. */
    private fun roundsTo(value: Double, places: Int, target: BigDecimal): Boolean =
        BigDecimal(value).setScale(places, RoundingMode.HALF_EVEN).compareTo(target) == 0

    private fun isGrounded(claim: Claim, pool: List<Double>): Boolean {
        val places = precision(claim)
        val rescalings = listOf(AS_WRITTEN) + (UNIT_RESCALINGS[claim.unit ?: ""] ?: emptyList())
        for (source in pool) {
            for ((multiply, divide) in rescalings) {
                for (multiplier in multipliers(claim.suffix)) {
                    // Same operations in the same order as Python, so the doubles match.
                    val value = source * multiply / divide / multiplier
                    if (roundsTo(value, places, claim.mantissa)) return true
                }
            }
        }
        return false
    }

    fun check(answer: String, sources: List<String>): Grounding {
        val pool = poolFrom(sources)
        val verified = mutableListOf<String>()
        val unverified = mutableListOf<String>()
        for (claim in claimsIn(answer)) {
            (if (isGrounded(claim, pool)) verified else unverified) += claim.text
        }
        return Grounding(verified, unverified)
    }
}
