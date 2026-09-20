package dev.aura.core

/**
 * The canonical Aura schema.
 *
 * `schema.sql` is generated from the Python migrations by
 * `scripts/export_schema.py`, so the phone and the server get their tables and
 * metrics views from one source rather than two that drift. A test on the
 * Python side fails if the file falls behind the migrations.
 */
object Schema {
    const val RESOURCE_PATH: String = "/aura/schema.sql"

    /** The generated DDL, read from the packaged resource. */
    fun sql(): String =
        Schema::class.java.getResourceAsStream(RESOURCE_PATH)
            ?.bufferedReader()
            ?.use { it.readText() }
            ?: error(
                "$RESOURCE_PATH is missing from the classpath. " +
                    "Run scripts/export_schema.py to generate it."
            )

    /**
     * The DDL split into executable statements.
     *
     * Comment lines go first, then a plain split on `;` — safe here because no
     * literal in the generated schema contains one, which `SchemaTest` checks
     * rather than assumes.
     */
    fun statements(sql: String = sql()): List<String> =
        sql.lineSequence()
            .filterNot { it.trimStart().startsWith("--") }
            .joinToString("\n")
            .split(';')
            .map { it.trim() }
            .filter { it.isNotEmpty() }

    /** Build an empty database: tables, indexes and views. */
    fun create(db: Db, sql: String = sql()) {
        statements(sql).forEach { db.execute(it) }
    }
}
