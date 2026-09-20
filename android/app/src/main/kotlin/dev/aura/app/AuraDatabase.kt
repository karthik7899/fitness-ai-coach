package dev.aura.app

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import dev.aura.core.Db
import dev.aura.core.Schema

/**
 * Opens the app's database, creating it from the shared schema on first run.
 *
 * The schema is not declared here. It is generated from the Python migrations
 * and packaged with :core, so this module has no opinion about the shape of the
 * database at all — which is the only way two apps stay in agreement about it.
 */
class AuraDatabase(context: Context) :
    SQLiteOpenHelper(context, DATABASE_NAME, null, SCHEMA_VERSION) {

    override fun onCreate(database: SQLiteDatabase) {
        Schema.create(AndroidDb(database))
    }

    override fun onUpgrade(database: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        // Deliberately not implemented yet. The Python side owns migrations;
        // until the same sequence is replayable here, a silent best-effort
        // upgrade would be worse than a loud stop.
        throw UnsupportedOperationException(
            "No migration from $oldVersion to $newVersion. Export a backup first."
        )
    }

    override fun onConfigure(database: SQLiteDatabase) {
        // Off by default, so ON DELETE CASCADE would silently strand rows.
        database.setForeignKeyConstraintsEnabled(true)
    }

    fun open(): Db = AndroidDb(writableDatabase)

    companion object {
        const val DATABASE_NAME = "aura.db"

        /**
         * Bumped only when the generated schema changes shape. It tracks the
         * Alembic revision in schema.sql rather than leading it.
         */
        const val SCHEMA_VERSION = 1
    }
}
