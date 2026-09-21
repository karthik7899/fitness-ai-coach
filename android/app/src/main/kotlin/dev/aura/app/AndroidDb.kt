package dev.aura.app

import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import dev.aura.core.Db
import dev.aura.core.Row

/**
 * [Db] over Android's own SQLite.
 *
 * The counterpart to the JDBC implementation the tests use. Both drive the same
 * engine with the same SQL, which is what lets the metrics be proved off-device.
 */
class AndroidDb(private val database: SQLiteDatabase) : Db {

    override fun execute(sql: String, args: List<Any?>) {
        if (args.isEmpty()) {
            database.execSQL(sql)
        } else {
            database.execSQL(sql, args.map { bindable(it) }.toTypedArray())
        }
    }

    /**
     * execSQL binds only String, Long, Double, byte[] and null — an Int throws.
     * JDBC takes any of them, so without this the importers would pass their
     * tests off-device and crash on the phone.
     */
    private fun bindable(value: Any?): Any? =
        when (value) {
            null, is String, is Long, is Double, is ByteArray -> value
            is Boolean -> if (value) 1L else 0L
            is Int, is Short, is Byte -> (value as Number).toLong()
            is Float -> value.toDouble()
            is Number -> value.toDouble()
            else -> value.toString()
        }

    override fun <T> select(sql: String, args: List<Any?>, map: (Row) -> T): List<T> {
        // rawQuery binds every argument as text, so a numeric one would compare
        // differently here than under JDBC. Fail loudly rather than quietly
        // return the wrong rows; put the number in the SQL, or cast it there.
        require(args.all { it == null || it is String }) {
            "select() arguments must be strings on Android: ${args.filterNot { it is String? }}"
        }
        return database.rawQuery(sql, args.map { it as String? }.toTypedArray()).use { cursor ->
            val row = CursorRow(cursor)
            buildList { while (cursor.moveToNext()) add(map(row)) }
        }
    }

    override fun close() = database.close()
}

private class CursorRow(private val cursor: Cursor) : Row {
    private fun index(column: String) = cursor.getColumnIndexOrThrow(column)

    override fun isNull(column: String): Boolean = cursor.isNull(index(column))

    override fun stringOrNull(column: String): String? =
        index(column).let { if (cursor.isNull(it)) null else cursor.getString(it) }

    override fun longOrNull(column: String): Long? =
        index(column).let { if (cursor.isNull(it)) null else cursor.getLong(it) }

    override fun doubleOrNull(column: String): Double? =
        index(column).let { if (cursor.isNull(it)) null else cursor.getDouble(it) }
}
