package dev.aura.core.imports

import dev.aura.core.Db
import java.math.BigDecimal
import java.math.RoundingMode

/**
 * Shared helpers for reading someone else's database.
 *
 * Both importers read files written by other apps, whose schemas vary by
 * version and by device. Rather than assume a shape, they discover it: ask what
 * tables and columns exist, and pick from a list of known names.
 */
internal object Parsing {

    fun tables(db: Db): List<String> =
        db.select("SELECT name FROM sqlite_master WHERE type = 'table'") { it.string("name") }

    fun columns(db: Db, table: String): List<String> =
        db.select("PRAGMA table_info(\"$table\")") { it.string("name") }

    /** The first candidate that exists, matched without regard to case. */
    fun pick(available: List<String>, vararg candidates: String): String? {
        val lowered = available.associateBy { it.lowercase() }
        return candidates.firstNotNullOfOrNull { lowered[it.lowercase()] }
    }
}

/**
 * Rounding, matched to Python's.
 *
 * `round()` on a Decimal is half-to-even there, and the importers round weights
 * to three places and distances to two. Half-up here would disagree on exactly
 * the values that land on a midpoint — rare, but silent, and the whole point of
 * the shared fixtures is that the two implementations cannot differ.
 */
internal fun BigDecimal.roundTo(places: Int): BigDecimal =
    setScale(places, RoundingMode.HALF_EVEN)

internal val LBS_TO_KG: BigDecimal = BigDecimal("0.45359237")
internal val MILES_TO_M: BigDecimal = BigDecimal("1609.344")
internal val KM_TO_M: BigDecimal = BigDecimal("1000")
