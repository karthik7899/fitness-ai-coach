package dev.aura.core

import dev.aura.core.imports.FitNotesImport
import dev.aura.core.imports.GadgetbridgeImport
import java.io.File
import java.time.ZoneId
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import org.junit.jupiter.api.Test

/**
 * The Kotlin importers, held to the same rows the Python ones produce.
 *
 * The fixtures in `fixtures/` are the contract: the same backup file, the same
 * canonical rows, whichever app read it. See `fixtures/README.md` for why the
 * comparison is done as text rendered by SQLite.
 */
class ImportTest {

    private val fixtures = File(System.getProperty("aura.fixtures") ?: "../fixtures")

    /** Stand up the database some other app would have written. */
    private fun sourceFrom(name: String): JdbcDb {
        val script = fixtures.resolve("$name.source.sql").readText()
        return JdbcDb.blank().also { db ->
            // Same comment-stripping and statement splitting the schema uses.
            Schema.statements(script).forEach { db.execute(it) }
        }
    }

    private fun expected(name: String): List<String> =
        fixtures.resolve("$name.expected.csv").readLines().filter { it.isNotBlank() }

    private fun rows(db: Db, query: String): List<String> =
        db.select(fixtures.resolve(query).readText()) { it.string("line") }

    private fun importFitNotes(name: String): List<String> =
        sourceFrom(name).use { source ->
            JdbcDb.inMemory().use { target ->
                FitNotesImport.run(source, target)
                rows(target, "rows_fitnotes.sql")
            }
        }

    @Test
    fun `the fixtures are actually present`() {
        assertTrue(
            fixtures.resolve("rows_fitnotes.sql").exists(),
            "Fixtures not found at ${fixtures.absolutePath}",
        )
    }

    @Test
    fun `a FitNotes backup with metric weights`() {
        assertEquals(expected("fitnotes_metric"), importFitNotes("fitnotes_metric"))
    }

    @Test
    fun `an older FitNotes backup in pounds and miles`() {
        assertEquals(expected("fitnotes_imperial"), importFitNotes("fitnotes_imperial"))
    }

    @Test
    fun `re-importing the same backup does not duplicate anything`() {
        sourceFrom("fitnotes_metric").use { source ->
            JdbcDb.inMemory().use { target ->
                val first = FitNotesImport.run(source, target)
                val second = FitNotesImport.run(source, target)
                assertEquals(first.written, second.written)
                assertEquals(expected("fitnotes_metric"), rows(target, "rows_fitnotes.sql"))
            }
        }
    }

    @Test
    fun `a Gadgetbridge export`() {
        sourceFrom("gadgetbridge").use { source ->
            JdbcDb.inMemory().use { target ->
                GadgetbridgeImport.run(source, target, ZoneId.of("UTC"))
                assertEquals(expected("gadgetbridge"), rows(target, "rows_gadgetbridge.sql"))
            }
        }
    }

    @Test
    fun `re-importing an export updates in place`() {
        sourceFrom("gadgetbridge").use { source ->
            JdbcDb.inMemory().use { target ->
                GadgetbridgeImport.run(source, target, ZoneId.of("UTC"))
                GadgetbridgeImport.run(source, target, ZoneId.of("UTC"))
                assertEquals(expected("gadgetbridge"), rows(target, "rows_gadgetbridge.sql"))
            }
        }
    }

    @Test
    fun `a table that is not a sample table is ignored`() {
        sourceFrom("gadgetbridge").use { source ->
            assertEquals(listOf("MOYOUNG_ACTIVITY_SAMPLE"), GadgetbridgeImport.sampleTables(source))
        }
    }

    @Test
    fun `an unrelated database is not mistaken for an export`() {
        JdbcDb.inMemory().use { notAnExport ->
            assertTrue(!GadgetbridgeImport.looksLikeGadgetbridge(notAnExport))
        }
    }

    @Test
    fun `imported sets land under their own source, away from anything logged`() {
        sourceFrom("fitnotes_metric").use { source ->
            JdbcDb.inMemory().use { target ->
                FitNotesImport.run(source, target)
                val sources =
                    target.select("SELECT DISTINCT source FROM workouts") { it.string("source") }
                assertEquals(listOf("fitnotes_import"), sources)
            }
        }
    }
}
