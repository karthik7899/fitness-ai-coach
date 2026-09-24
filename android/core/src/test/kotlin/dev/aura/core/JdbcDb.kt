package dev.aura.core

import java.sql.Connection
import java.sql.DriverManager
import java.sql.ResultSet

/**
 * A [Db] backed by JDBC, so the real schema and the real views run off-device.
 *
 * This is the whole reason [Db] is an interface: SQLite on Android and SQLite
 * under JDBC are the same engine running the same SQL, so anything these tests
 * prove about the views holds on the phone as well.
 */
class JdbcDb(private val connection: Connection) : Db {

    override fun execute(sql: String, args: List<Any?>) {
        if (args.isEmpty()) {
            connection.createStatement().use { it.execute(sql) }
            return
        }
        connection.prepareStatement(sql).use { statement ->
            args.forEachIndexed { index, value -> statement.setObject(index + 1, value) }
            statement.execute()
        }
    }

    override fun <T> select(sql: String, args: List<Any?>, map: (Row) -> T): List<T> {
        // The same rule AndroidDb enforces, where rawQuery binds everything as
        // text. Without it here, a query passing a number works in every test
        // and throws on the phone.
        require(args.all { it == null || it is String }) {
            "select() arguments must be strings on Android: ${args.filterNot { it is String? }}"
        }
        return connection.prepareStatement(sql).use { statement ->
            args.forEachIndexed { index, value -> statement.setObject(index + 1, value) }
            statement.executeQuery().use { results ->
                val row = JdbcRow(results)
                buildList { while (results.next()) add(map(row)) }
            }
        }
    }

    override fun close() = connection.close()

    companion object {
        /** A fresh empty database with the canonical schema applied. */
        fun inMemory(): JdbcDb = blank().also { Schema.create(it) }

        /**
         * A database with nothing in it, for standing up a file some other app
         * wrote — a FitNotes backup or a Gadgetbridge export.
         */
        fun blank(): JdbcDb {
            val connection = DriverManager.getConnection("jdbc:sqlite::memory:")
            // Off by default, so ON DELETE CASCADE would silently do nothing —
            // the same correction the Python side makes.
            connection.createStatement().use { it.execute("PRAGMA foreign_keys=ON") }
            return JdbcDb(connection)
        }
    }
}

private class JdbcRow(private val results: ResultSet) : Row {
    override fun isNull(column: String): Boolean {
        results.getObject(column)
        return results.wasNull()
    }

    override fun columns(): List<String> =
        results.metaData.let { meta -> (1..meta.columnCount).map { meta.getColumnLabel(it) } }

    override fun value(column: String): Any? =
        when (val raw = results.getObject(column)) {
            null -> null
            is String -> raw
            is Int, is Long, is Short, is Byte -> (raw as Number).toLong()
            is Number -> raw.toDouble()
            is Boolean -> if (raw) 1L else 0L
            else -> raw.toString()
        }

    override fun stringOrNull(column: String): String? = results.getString(column)

    override fun longOrNull(column: String): Long? =
        results.getLong(column).takeUnless { results.wasNull() }

    override fun doubleOrNull(column: String): Double? =
        results.getDouble(column).takeUnless { results.wasNull() }
}
