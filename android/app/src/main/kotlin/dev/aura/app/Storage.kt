package dev.aura.app

import android.content.Context
import android.content.Intent
import android.database.sqlite.SQLiteDatabase
import android.net.Uri
import androidx.documentfile.provider.DocumentFile
import dev.aura.core.Db
import java.io.File

/**
 * Reading files that belong to other apps.
 *
 * Through the Storage Access Framework rather than a storage permission, which
 * is why the manifest asks for nothing: you pick the FitNotes and Gadgetbridge
 * folders once, and the app gets exactly those and nothing else. Asking for
 * access to all files in order to read two folders is the kind of request that
 * teaches people to stop reading permission dialogs.
 */
class Storage(private val context: Context) {

    /** A file in a folder the user granted us. */
    data class Entry(val name: String, val uri: Uri, val bytes: Long)

    /**
     * Keep access across restarts.
     *
     * Without this the grant lasts until the process dies, and the next
     * scheduled import finds nothing it is allowed to read.
     */
    fun persist(tree: Uri) {
        context.contentResolver.takePersistableUriPermission(
            tree,
            Intent.FLAG_GRANT_READ_URI_PERMISSION,
        )
    }

    fun release(tree: Uri) {
        runCatching {
            context.contentResolver.releasePersistableUriPermission(
                tree,
                Intent.FLAG_GRANT_READ_URI_PERMISSION,
            )
        }
    }

    /** The folders we still hold a grant for, which may be fewer than were chosen. */
    fun grantedFolders(): List<Uri> =
        context.contentResolver.persistedUriPermissions
            .filter { it.isReadPermission }
            .map { it.uri }

    fun displayName(tree: Uri): String =
        DocumentFile.fromTreeUri(context, tree)?.name ?: tree.lastPathSegment ?: tree.toString()

    fun filesIn(tree: Uri): List<Entry> =
        DocumentFile.fromTreeUri(context, tree)
            ?.listFiles()
            ?.filter { it.isFile }
            ?.mapNotNull { file ->
                val name = file.name ?: return@mapNotNull null
                Entry(name, file.uri, file.length())
            }
            .orEmpty()

    /**
     * Copy a document somewhere SQLite can open it.
     *
     * SQLite needs a path on a real filesystem; a content:// URI is a stream,
     * and there is no way to hand one to the database engine.
     */
    fun copyToCache(uri: Uri, name: String): File {
        val scratch = File(context.cacheDir, "import").also { it.mkdirs() }
        val destination = File(scratch, name)
        context.contentResolver.openInputStream(uri).use { input ->
            requireNotNull(input) { "Could not open $name." }
            destination.outputStream().use { output -> input.copyTo(output) }
        }
        return destination
    }

    /** Open a copied file read-only. Nothing we import from is ever written to. */
    fun openReadOnly(file: File): Db =
        AndroidDb(
            SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READONLY)
        )

    fun writeTo(uri: Uri, source: File) {
        context.contentResolver.openOutputStream(uri).use { output ->
            requireNotNull(output) { "Could not write to the chosen location." }
            source.inputStream().use { input -> input.copyTo(output) }
        }
    }

    /** Cached copies are working files; nothing should survive the operation. */
    fun clearCache() {
        File(context.cacheDir, "import").deleteRecursively()
    }
}
