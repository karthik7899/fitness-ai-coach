package dev.aura.core.imports

import dev.aura.core.Db
import java.time.ZoneId

/**
 * What a file turned out to be.
 *
 * Identified by its contents rather than its name: Gadgetbridge's export is
 * called `Gadgetbridge` with no extension at all, and a FitNotes backup can be
 * named anything you like.
 */
enum class FileKind {
    FITNOTES,
    GADGETBRIDGE,
    /** A readable database, but not one of ours. A watched folder is full of these. */
    UNKNOWN,
}

data class ImportResult(val kind: FileKind, val read: Int, val written: Int) {
    val isEmpty: Boolean
        get() = written == 0
}

/**
 * Recognising and importing a file someone else's app wrote.
 *
 * The same rules as the Python inbox, which is the point: a folder watched by
 * both apps must not have one of them import a file the other ignores.
 */
object Inbox {

    /** Identify an already-opened SQLite database by the tables it has. */
    fun identify(source: Db): FileKind {
        val tables = Parsing.tables(source).map { it.lowercase() }.toSet()
        return when {
            tables.isEmpty() -> FileKind.UNKNOWN
            tables.containsAll(listOf("training_log", "exercise")) -> FileKind.FITNOTES
            tables.any { it.endsWith("activity_sample") } -> FileKind.GADGETBRIDGE
            else -> FileKind.UNKNOWN
        }
    }

    /**
     * Import whatever [source] turns out to be.
     *
     * An unrecognised file is not an error. Watched folders belong to other
     * apps and are full of files that are none of our business.
     */
    fun importFrom(
        source: Db,
        target: Db,
        zone: ZoneId = ZoneId.systemDefault(),
    ): ImportResult =
        when (val kind = identify(source)) {
            FileKind.FITNOTES -> {
                val parsed = FitNotesImport.parse(source)
                val outcome = FitNotesImport.store(target, parsed)
                ImportResult(kind, outcome.read, outcome.written)
            }
            FileKind.GADGETBRIDGE -> {
                val readings = GadgetbridgeImport.extract(source, zone)
                val outcome = GadgetbridgeImport.store(target, readings)
                ImportResult(kind, outcome.read, outcome.written)
            }
            FileKind.UNKNOWN -> ImportResult(kind, read = 0, written = 0)
        }
}
