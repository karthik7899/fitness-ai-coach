package dev.aura.core

import java.io.File
import java.sql.DriverManager
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir

class BackupTest {

    private fun onDisk(file: File): JdbcDb {
        val connection = DriverManager.getConnection("jdbc:sqlite:${file.absolutePath}")
        connection.createStatement().use { it.execute("PRAGMA foreign_keys=ON") }
        return JdbcDb(connection)
    }

    private fun populated(file: File): JdbcDb =
        onDisk(file).also { db ->
            Schema.create(db)
            db.seedExercises()
            db.addWorkout(TODAY, listOf(SetSpec("Back Squat", 100.0, 5)))
            db.addDailyMetric(TODAY, "steps", "gadgetbridge", 6000.0, "count")
        }

    @Test
    fun `a backup describes what it holds`(@TempDir dir: File) {
        val live = dir.resolve("aura.db")
        populated(live).use { db ->
            Backup.checkpoint(db)
            val info = Backup.describe(db)
            assertEquals(1, info.workouts)
            assertEquals(1, info.sets)
            assertEquals(1, info.dailyMetrics)
            assertEquals(TODAY.toString(), info.earliest)
            assertTrue(!info.isEmpty)
        }
    }

    @Test
    fun `a copy taken after a checkpoint carries the latest writes`(@TempDir dir: File) {
        val live = dir.resolve("aura.db")
        val backup = dir.resolve("backup.db")

        populated(live).use { db ->
            // The write that matters is the last one, which is the one a naive
            // copy is most likely to leave behind in the -wal file.
            db.addWorkout(TODAY, listOf(SetSpec("Bench Press", 80.0, 8)))
            Backup.checkpoint(db)
            live.copyTo(backup, overwrite = true)
        }

        onDisk(backup).use { restored ->
            val info = Backup.verify(restored)
            assertEquals(2, info.workouts)
            assertEquals(2, info.sets)
        }
    }

    @Test
    fun `the restored copy answers the same metrics as the original`(@TempDir dir: File) {
        val live = dir.resolve("aura.db")
        val backup = dir.resolve("backup.db")

        val before =
            populated(live).use { db ->
                Backup.checkpoint(db)
                live.copyTo(backup, overwrite = true)
                Metrics(db).volumeByDay(TODAY, TODAY)
            }

        onDisk(backup).use { restored ->
            Backup.verify(restored)
            // Not just the rows: the views have to work too, since that is
            // where every number the coach quotes comes from.
            assertEquals(before, Metrics(restored).volumeByDay(TODAY, TODAY))
        }
    }

    @Test
    fun `a SQLite file that is not an Aura database is refused`(@TempDir dir: File) {
        val stranger = dir.resolve("something-else.db")
        onDisk(stranger).use { db ->
            db.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
            val problem = assertFailsWith<Backup.NotABackup> { Backup.verify(db) }
            assertTrue(
                problem.message!!.contains("not an Aura backup"),
                "the reason should say what is wrong: ${problem.message}",
            )
        }
    }

    @Test
    fun `an empty but valid database is a backup, just an empty one`(@TempDir dir: File) {
        val fresh = dir.resolve("fresh.db")
        onDisk(fresh).use { db ->
            Schema.create(db)
            val info = Backup.verify(db)
            assertTrue(info.isEmpty)
            assertEquals(null, info.earliest)
        }
    }

    @Test
    fun `a truncated file is refused rather than half-restored`(@TempDir dir: File) {
        val live = dir.resolve("aura.db")
        val damaged = dir.resolve("damaged.db")
        populated(live).use { Backup.checkpoint(it) }

        // Keep the SQLite header so it is recognisably a database, and lose the
        // rest — the shape a partial copy or an interrupted transfer takes.
        val bytes = live.readBytes()
        damaged.writeBytes(bytes.copyOfRange(0, bytes.size / 3))

        assertFailsWith<Exception> { onDisk(damaged).use { Backup.verify(it) } }
    }
}
