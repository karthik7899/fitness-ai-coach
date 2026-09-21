package dev.aura.core

/**
 * One row of a result, addressed by column name.
 *
 * Deliberately small. There are two implementations — a JDBC `ResultSet` off
 * the device and an Android `Cursor` on it — and this is roughly the whole of
 * what they agree on. Nullability is explicit because the two disagree about
 * it otherwise: JDBC's `getLong` returns 0 for NULL and expects a follow-up
 * `wasNull()`, which is exactly the kind of difference that turns a missing
 * reading into a real zero.
 */
interface Row {
    fun isNull(column: String): Boolean

    /** The result's column names, in order — needed to render a row as JSON. */
    fun columns(): List<String>

    /**
     * The column's value as SQLite typed it: String, Long, Double or null.
     *
     * The two backends disagree about the boxed type an integer comes back as,
     * so both normalise here rather than leaving callers to guess.
     */
    fun value(column: String): Any?

    fun stringOrNull(column: String): String?

    fun longOrNull(column: String): Long?

    fun doubleOrNull(column: String): Double?

    fun string(column: String): String = stringOrNull(column) ?: nullColumn(column)

    fun long(column: String): Long = longOrNull(column) ?: nullColumn(column)

    fun double(column: String): Double = doubleOrNull(column) ?: nullColumn(column)

    fun int(column: String): Int = long(column).toInt()

    fun boolean(column: String): Boolean = long(column) != 0L
}

private fun nullColumn(column: String): Nothing =
    throw IllegalStateException("Column '$column' was null; use the OrNull accessor if that is expected.")

/**
 * The database, as the rest of the app sees it.
 *
 * Statements use positional `?` placeholders, which is what both JDBC and
 * Android's SQLite bind. Nothing above this interface knows which one is in use.
 */
interface Db : AutoCloseable {
    fun execute(sql: String, args: List<Any?> = emptyList())

    fun <T> select(sql: String, args: List<Any?> = emptyList(), map: (Row) -> T): List<T>

    fun <T> selectOne(sql: String, args: List<Any?> = emptyList(), map: (Row) -> T): T? =
        select(sql, args, map).firstOrNull()
}
