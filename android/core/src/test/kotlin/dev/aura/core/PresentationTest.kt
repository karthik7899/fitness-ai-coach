package dev.aura.core

import dev.aura.core.presentation.Format
import dev.aura.core.presentation.LoadBand
import dev.aura.core.presentation.Range
import dev.aura.core.presentation.Store
import java.time.LocalDate
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue
import org.junit.jupiter.api.Test

/**
 * The screen layer.
 *
 * All of it lives here rather than in the Compose code so that it can be run
 * without a device — which matters more than usual, because the Compose module
 * cannot be built in this environment at all.
 */
class PresentationTest {

    private val today = LocalDate.of(2026, 9, 21)

    // ----------------------------------------------------------------------
    // Formatting
    // ----------------------------------------------------------------------

    @Test
    fun `whole numbers lose their decimals`() {
        // Trailing zeros on a training number read as precision that is not there.
        assertEquals("100", Format.number(100.0))
        assertEquals("102.5", Format.number(102.5))
        assertEquals("1.79", Format.number(1.7934))
    }

    @Test
    fun `thousands are grouped`() {
        assertEquals("1,000", Format.number(1000.0))
        assertEquals("10,872", Format.number(10872.0))
        assertEquals("1,234.5", Format.number(1234.5))
        assertEquals("-1,500", Format.number(-1500.0))
        assertEquals("999", Format.number(999.0))
    }

    @Test
    fun `big volumes are compact, small ones are not`() {
        assertEquals("500 kg", Format.compactKg(500.0))
        assertEquals("9,495 kg", Format.compactKg(9495.0))
        assertEquals("10.9K kg", Format.compactKg(10872.0))
        assertEquals("1.2M kg", Format.compactKg(1_234_000.0))
    }

    @Test
    fun `sleep is written in hours, not stored minutes`() {
        assertEquals("7h 30m", Format.metricValue("sleep_minutes", 450.0, "min"))
        assertEquals("45m", Format.metricValue("sleep_minutes", 45.0, "min"))
        assertEquals("6,000", Format.metricValue("steps", 6000.0, "count"))
        assertEquals("58 bpm", Format.metricValue("resting_hr", 58.0, "bpm"))
    }

    @Test
    fun `metric keys are written as words`() {
        assertEquals("Resting HR", Format.metricName("resting_hr"))
        assertEquals("HRV", Format.metricName("hrv_ms"))
        assertEquals("Steps", Format.metricName("steps"))
    }

    @Test
    fun `recent days are named rather than dated`() {
        assertEquals("Today", Format.day(today, today))
        assertEquals("Yesterday", Format.day(today.minusDays(1), today))
        assertEquals("1 Sep", Format.day(LocalDate.of(2026, 9, 1), today))
        assertEquals("1 Sep 2025", Format.day(LocalDate.of(2025, 9, 1), today))
    }

    @Test
    fun `a missing ratio is a dash, not a zero`() {
        // Zero would read as "no load"; the truth is "not enough history yet".
        assertEquals("—", Format.ratio(null))
        assertEquals("1.79", Format.ratio(1.7934))
    }

    @Test
    fun `load bands match the thresholds the coach quotes`() {
        assertEquals(LoadBand.UNKNOWN, LoadBand.of(null))
        assertEquals(LoadBand.DETRAINING, LoadBand.of(0.6))
        assertEquals(LoadBand.STEADY, LoadBand.of(1.0))
        assertEquals(LoadBand.STEADY, LoadBand.of(1.3))
        assertEquals(LoadBand.STRETCHED, LoadBand.of(1.45))
        assertEquals(LoadBand.SPIKE, LoadBand.of(1.9))
    }

    // ----------------------------------------------------------------------
    // The store
    // ----------------------------------------------------------------------

    private fun withStore(block: (Db, Store) -> Unit) =
        JdbcDb.inMemory().use { db ->
            db.seedExercises()
            block(db, Store(db))
        }

    @Test
    fun `the dashboard reads the same numbers the views hold`() {
        withStore { db, store ->
            db.addWorkout(TODAY, listOf(SetSpec("Back Squat", 100.0, 5)))
            db.addDailyMetric(TODAY, "steps", "gadgetbridge", 6000.0, "count")

            val state = store.dashboard(TODAY)
            assertEquals(listOf("steps"), state.wellness.map { it.metric })
            assertEquals(0.5, state.load?.loadAu)
            assertEquals(listOf(TODAY), state.recent.map { it.date })
        }
    }

    @Test
    fun `trends builds two series over the same dates`() {
        withStore { db, store ->
            db.addWorkout(TODAY, listOf(SetSpec("Back Squat", 100.0, 5)))
            val state = store.trends(Range.MONTH, today = TODAY)

            assertEquals(31, state.acute.points.size)
            assertEquals(
                state.acute.points.map { it.date },
                state.chronic.points.map { it.date },
                "the two series must share an x axis, or the chart lies",
            )
            assertEquals("Back Squat", state.progressionFor)
            assertTrue(state.byMuscle.isNotEmpty())
        }
    }

    @Test
    fun `trends picks the heaviest-trained exercise when none is chosen`() {
        withStore { db, store ->
            db.addWorkout(TODAY, listOf(SetSpec("Back Squat", 100.0, 5)))
            db.addWorkout(TODAY, listOf(SetSpec("Bench Press", 80.0, 10)))
            // Bench: 800kg beats squat's 500kg.
            assertEquals("Bench Press", store.trends(today = TODAY).progressionFor)
            assertEquals("Back Squat", store.trends(exercise = "Back Squat", today = TODAY).progressionFor)
        }
    }

    @Test
    fun `an empty database still produces a screen`() {
        withStore { _, store ->
            val dashboard = store.dashboard(TODAY)
            assertTrue(dashboard.recent.isEmpty())
            assertEquals(LoadBand.UNKNOWN, dashboard.band)
            assertNull(store.trends(today = TODAY).progressionFor)
            assertTrue(store.log(TODAY).sets.isEmpty())
        }
    }

    @Test
    fun `logging a set puts it where the views can see it`() {
        withStore { _, store ->
            store.addSet("Back Squat", 120.0, 3, day = TODAY)
            val log = store.log(TODAY)
            assertEquals(1, log.sets.size)
            assertEquals("Back Squat", log.sets.single().exercise)
            // And the metrics agree: 120 x 3 = 360kg.
            assertEquals(360.0, store.dashboard(TODAY).recent.single().volumeKg)
        }
    }

    @Test
    fun `logging an unknown exercise creates it rather than refusing`() {
        withStore { db, store ->
            store.addSet("Jefferson Curl", 40.0, 8, day = TODAY)
            val names = db.select("SELECT name FROM exercises") { it.string("name") }
            assertTrue("Jefferson Curl" in names)
        }
    }

    @Test
    fun `sets logged on one day stack in order`() {
        withStore { _, store ->
            store.addSet("Back Squat", 60.0, 10, isWarmup = true, day = TODAY)
            store.addSet("Back Squat", 100.0, 5, day = TODAY)
            val sets = store.log(TODAY).sets
            assertEquals(listOf(true, false), sets.map { it.isWarmup })
            // The warmup is stored, but must not reach the volume.
            assertEquals(500.0, store.dashboard(TODAY).recent.single().volumeKg)
        }
    }

    @Test
    fun `a deleted set leaves nothing behind`() {
        withStore { _, store ->
            store.addSet("Back Squat", 100.0, 5, day = TODAY)
            store.deleteSet(store.log(TODAY).sets.single().id)
            assertTrue(store.log(TODAY).sets.isEmpty())
            assertTrue(store.dashboard(TODAY).recent.isEmpty())
        }
    }

    @Test
    fun `the exercise suggestions are the ones trained most recently`() {
        withStore { _, store ->
            store.addSet("Back Squat", 100.0, 5, day = TODAY.minusDays(3))
            store.addSet("Bench Press", 80.0, 5, day = TODAY)
            assertEquals(listOf("Bench Press", "Back Squat"), store.log(TODAY).recentExercises)
        }
    }

    // ----------------------------------------------------------------------
    // Settings
    // ----------------------------------------------------------------------

    @Test
    fun `the settings screen never receives the key itself`() {
        withStore { db, store ->
            Settings.saveGemini(db, "placeholder-not-a-real-key-wxyz", null)
            val state = store.settings()
            assertEquals("…wxyz", state.apiKeyHint)
            assertTrue(
                state.apiKeyHint!!.length < 10,
                "the screen must not be able to print the key",
            )
        }
    }

    @Test
    fun `saving a model keeps the key, and clearing the key keeps the model`() {
        withStore { db, store ->
            Settings.saveGemini(db, "secret-key-1234", null)
            Settings.saveGemini(db, null, "gemini-3.8-pro")
            assertEquals("secret-key-1234", Settings.apiKey(db))
            assertEquals("gemini-3.8-pro", Settings.model(db))

            Settings.clearApiKey(db)
            assertNull(Settings.apiKey(db))
            assertEquals("gemini-3.8-pro", Settings.model(db), "clearing the key lost the model")
            assertNull(store.settings().apiKeyHint)
        }
    }

    @Test
    fun `watch folders round trip and drop the blanks`() {
        withStore { db, store ->
            Settings.saveWatchFolders(db, listOf(" /storage/FitNotes ", "", "/storage/GB"))
            assertEquals(
                listOf("/storage/FitNotes", "/storage/GB"),
                store.settings().watchFolders,
            )
        }
    }

    @Test
    fun `an unset key reads as unset rather than as an empty string`() {
        withStore { db, store ->
            assertNull(store.settings().apiKeyHint)
            assertEquals(Settings.DEFAULT_MODEL, store.settings().model)
            Settings.saveGemini(db, "   ", null)
            assertNull(Settings.apiKey(db))
        }
    }
}
