package dev.aura.core.imports

import dev.aura.core.Db
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/**
 * Imports a Gadgetbridge export — watch data with no vendor or Google involved.
 *
 * Gadgetbridge talks to Moyoung/CRRepa watches (the ones the Da Fit app ships
 * with) directly over Bluetooth, so the data never reaches Moyoung's servers or
 * Google's. Its Data Export writes a SQLite database, which this reads.
 *
 * Samples live in per-device tables (`MI_BAND_ACTIVITY_SAMPLE`,
 * `MOYOUNG_ACTIVITY_SAMPLE`, ...) that share a column shape, and which tables
 * exist depends on what you have paired — so the tables are discovered rather
 * than named.
 *
 * Sleep is deliberately conservative. Gadgetbridge stores a device-specific
 * RAW_KIND and normalises it only on read, so a kind value cannot be mapped to
 * sleep without knowing the device. Steps and heart rate are read directly;
 * sleep is emitted only where the export carries an explicitly typed KIND.
 */
object GadgetbridgeImport {

    const val SOURCE = "gadgetbridge"

    const val METRIC_STEPS = "steps"
    const val METRIC_RESTING_HR = "resting_hr"
    const val METRIC_SLEEP_MINUTES = "sleep_minutes"

    private const val SAMPLE_TABLE_SUFFIX = "ACTIVITY_SAMPLE"
    private val SLEEP_KINDS = setOf(2L, 4L, 16L) // light, deep, REM

    private val UNITS =
        mapOf(METRIC_STEPS to "count", METRIC_RESTING_HR to "bpm", METRIC_SLEEP_MINUTES to "min")

    /** A reading, ready for `daily_metrics`. */
    data class Reading(val date: LocalDate, val metric: String, val value: Double)

    fun sampleTables(source: Db): List<String> =
        Parsing.tables(source).filter { it.uppercase().endsWith(SAMPLE_TABLE_SUFFIX) }

    fun looksLikeGadgetbridge(source: Db): Boolean = sampleTables(source).isNotEmpty()

    /**
     * Reduce the export to one value per metric per day.
     *
     * [zone] decides which day a sample belongs to. It is the device's own zone
     * in normal use — you want the steps on the day you walked them — which
     * also means the same export can bucket differently in two places. The
     * tests pin it so the two implementations can be compared.
     */
    fun extract(source: Db, zone: ZoneId = ZoneId.systemDefault()): List<Reading> {
        val steps = mutableMapOf<LocalDate, Long>()
        val heartRates = mutableMapOf<LocalDate, MutableList<Double>>()
        val sleepMinutes = mutableMapOf<LocalDate, Double>()

        for (table in sampleTables(source)) {
            val cols = Parsing.columns(source, table)
            val timestamp = Parsing.pick(cols, "TIMESTAMP") ?: continue
            val stepsColumn = Parsing.pick(cols, "STEPS")
            val heartRateColumn = Parsing.pick(cols, "HEART_RATE")
            val kindColumn = Parsing.pick(cols, "KIND")

            fun column(name: String?, alias: String) =
                if (name != null) "\"$name\" AS $alias" else "NULL AS $alias"

            source.select(
                """
                SELECT "$timestamp" AS ts, ${column(stepsColumn, "steps")},
                       ${column(heartRateColumn, "hr")}, ${column(kindColumn, "kind")}
                FROM "$table"
                """
            ) { row ->
                Triple(
                    row.longOrNull("ts"),
                    row.longOrNull("steps") to row.doubleOrNull("hr"),
                    row.longOrNull("kind"),
                )
            }
                .forEach { (ts, stepsAndHr, kind) ->
                    if (ts == null) return@forEach
                    // Gadgetbridge timestamps are epoch seconds.
                    val day = Instant.ofEpochSecond(ts).atZone(zone).toLocalDate()

                    val (stepValue, heartRate) = stepsAndHr
                    if (stepValue != null && stepValue != 0L) {
                        steps[day] = (steps[day] ?: 0L) + stepValue
                    }
                    // 0 means "not measured"; under 25bpm is noise, not a reading.
                    if (heartRate != null && heartRate >= 25) {
                        heartRates.getOrPut(day) { mutableListOf() }.add(heartRate)
                    }
                    if (kind != null && kind in SLEEP_KINDS) {
                        // Samples are one minute apart.
                        sleepMinutes[day] = (sleepMinutes[day] ?: 0.0) + 1.0
                    }
                }
        }

        val readings = mutableListOf<Reading>()
        steps.forEach { (day, value) -> readings += Reading(day, METRIC_STEPS, value.toDouble()) }
        heartRates.forEach { (day, values) ->
            // Resting HR proxy: the low end of the day's distribution, which is
            // more robust than the single minimum sample.
            readings += Reading(day, METRIC_RESTING_HR, round1(percentile(values, 0.10)))
        }
        sleepMinutes.forEach { (day, minutes) ->
            readings += Reading(day, METRIC_SLEEP_MINUTES, round1(minutes))
        }
        return readings.sortedWith(compareBy({ it.date }, { it.metric }))
    }

    fun store(target: Db, readings: List<Reading>): ImportOutcome {
        readings.forEach { reading ->
            target.execute(
                """
                INSERT INTO daily_metrics (date, metric, source, value, unit)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (date, metric, source) DO UPDATE SET value = excluded.value
                """,
                listOf(
                    reading.date.toString(),
                    reading.metric,
                    SOURCE,
                    reading.value,
                    UNITS[reading.metric] ?: "",
                ),
            )
        }
        return ImportOutcome(read = readings.size, written = readings.size)
    }

    fun run(source: Db, target: Db, zone: ZoneId = ZoneId.systemDefault()): ImportOutcome =
        store(target, extract(source, zone))

    internal fun percentile(values: List<Double>, fraction: Double): Double {
        val ordered = values.sorted()
        val index = (ordered.size * fraction).toInt().coerceIn(0, ordered.size - 1)
        return ordered[index]
    }

    private fun round1(value: Double): Double = Math.round(value * 10.0) / 10.0
}
