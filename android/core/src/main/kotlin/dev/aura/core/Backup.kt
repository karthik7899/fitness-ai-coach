package dev.aura.core

/**
 * Backup and restore.
 *
 * The whole training history is one SQLite file on a device that gets lost,
 * wiped and replaced. A backup is therefore not a nicety, and one that turns
 * out to be unreadable is worse than none — so nothing here reports success
 * without having opened the result and looked at it.
 *
 * The backup format is the database itself. Anything that can open SQLite can
 * read it, including the desktop app, which matters because the two apps share
 * a schema and a backup is the way history moves between them.
 */
object Backup {

    /** Tables and views a file must have before it is treated as an Aura backup. */
    private val REQUIRED_TABLES =
        listOf("exercises", "workouts", "sets", "daily_metrics", "exercise_muscles")

    data class Info(
        val workouts: Int,
        val sets: Int,
        val exercises: Int,
        val dailyMetrics: Int,
        val earliest: String?,
        val latest: String?,
    ) {
        val isEmpty: Boolean
            get() = workouts == 0 && sets == 0 && dailyMetrics == 0
    }

    class NotABackup(message: String) : IllegalArgumentException(message)

    /**
     * Flush the write-ahead log into the main database file.
     *
     * Without this a copy of the file can be missing the most recent writes —
     * they are still sitting in the -wal sidecar, which the copy leaves behind.
     * The most recent writes are exactly the ones a backup is being taken for.
     */
    fun checkpoint(db: Db) {
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    }

    /**
     * Check that [candidate] is a readable Aura database, and describe it.
     *
     * Opening the file is the caller's job, because that is platform-specific.
     * Everything after it is not.
     */
    fun verify(candidate: Db): Info {
        val integrity =
            candidate.selectOne("PRAGMA integrity_check") { it.string("integrity_check") }
        if (integrity != "ok") {
            throw NotABackup("The file is a damaged database (integrity check said: $integrity).")
        }

        val present =
            candidate.select(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            ) { it.string("name") }.toSet()

        val missing = REQUIRED_TABLES.filterNot { it in present }
        if (missing.isNotEmpty()) {
            throw NotABackup(
                "This is a SQLite file but not an Aura backup: no ${missing.joinToString(", ")}."
            )
        }

        // A structural check rather than a version one: the schema carries no
        // version marker yet, because there has only ever been one shape of it.
        // The day a second exists, this needs to compare them.
        return describe(candidate)
    }

    /** Row counts and the span of history, for telling the user what they have. */
    fun describe(db: Db): Info {
        fun count(table: String) =
            db.selectOne("SELECT COUNT(*) AS n FROM \"$table\"") { it.int("n") } ?: 0

        val span =
            db.selectOne(
                "SELECT MIN(performed_on) AS first, MAX(performed_on) AS last FROM workouts"
            ) { it.stringOrNull("first") to it.stringOrNull("last") } ?: (null to null)

        return Info(
            workouts = count("workouts"),
            sets = count("sets"),
            exercises = count("exercises"),
            dailyMetrics = count("daily_metrics"),
            earliest = span.first,
            latest = span.second,
        )
    }
}
