package dev.aura.core

import dev.aura.core.imports.FileKind
import dev.aura.core.imports.Inbox
import java.io.File
import java.time.ZoneId
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import org.junit.jupiter.api.Test

/**
 * Recognising a file by its contents.
 *
 * Held to the same shared fixtures as the importers, because the cost of
 * getting this wrong is not a crash — it is a watched folder where one app
 * imports a file the other silently ignores.
 */
class InboxTest {

    private val fixtures = File(System.getProperty("aura.fixtures") ?: "../fixtures")

    private fun sourceFrom(name: String): JdbcDb =
        JdbcDb.blank().also { db ->
            Schema.statements(fixtures.resolve("$name.source.sql").readText())
                .forEach { db.execute(it) }
        }

    private fun expected(name: String): List<String> =
        fixtures.resolve("$name.expected.csv").readLines().filter { it.isNotBlank() }

    @Test
    fun `a FitNotes backup is recognised`() {
        sourceFrom("fitnotes_metric").use { assertEquals(FileKind.FITNOTES, Inbox.identify(it)) }
        sourceFrom("fitnotes_imperial").use { assertEquals(FileKind.FITNOTES, Inbox.identify(it)) }
    }

    @Test
    fun `a Gadgetbridge export is recognised`() {
        sourceFrom("gadgetbridge").use { assertEquals(FileKind.GADGETBRIDGE, Inbox.identify(it)) }
    }

    @Test
    fun `our own database is not mistaken for an import`() {
        // It is a perfectly good SQLite file sitting in the same folder as the
        // backups; importing it into itself would be a memorable bug.
        JdbcDb.inMemory().use { assertEquals(FileKind.UNKNOWN, Inbox.identify(it)) }
    }

    @Test
    fun `an unrelated database is left alone`() {
        JdbcDb.blank().use { db ->
            db.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
            assertEquals(FileKind.UNKNOWN, Inbox.identify(db))
        }
    }

    @Test
    fun `an empty file is unknown rather than an error`() {
        JdbcDb.blank().use { assertEquals(FileKind.UNKNOWN, Inbox.identify(it)) }
    }

    @Test
    fun `dispatch produces the same rows as calling the importer directly`() {
        sourceFrom("fitnotes_metric").use { source ->
            JdbcDb.inMemory().use { target ->
                val result = Inbox.importFrom(source, target)
                assertEquals(FileKind.FITNOTES, result.kind)
                assertTrue(result.written > 0)
                val rows =
                    target.select(fixtures.resolve("rows_fitnotes.sql").readText()) {
                        it.string("line")
                    }
                assertEquals(expected("fitnotes_metric"), rows)
            }
        }
    }

    @Test
    fun `dispatch handles a watch export too`() {
        sourceFrom("gadgetbridge").use { source ->
            JdbcDb.inMemory().use { target ->
                val result = Inbox.importFrom(source, target, ZoneId.of("UTC"))
                assertEquals(FileKind.GADGETBRIDGE, result.kind)
                val rows =
                    target.select(fixtures.resolve("rows_gadgetbridge.sql").readText()) {
                        it.string("line")
                    }
                assertEquals(expected("gadgetbridge"), rows)
            }
        }
    }

    @Test
    fun `an unknown file writes nothing and says so`() {
        JdbcDb.blank().use { source ->
            source.execute("CREATE TABLE shopping (item TEXT)")
            JdbcDb.inMemory().use { target ->
                val result = Inbox.importFrom(source, target)
                assertEquals(FileKind.UNKNOWN, result.kind)
                assertTrue(result.isEmpty)
            }
        }
    }
}
