package dev.aura.app

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import dev.aura.core.Backup
import dev.aura.core.Db
import dev.aura.core.Settings
import dev.aura.core.agent.Coach
import dev.aura.core.agent.CoachError
import dev.aura.core.agent.Conversation
import dev.aura.core.agent.Grounding
import dev.aura.core.agent.Trace
import dev.aura.core.imports.FileKind
import dev.aura.core.imports.Inbox
import dev.aura.core.presentation.DashboardState
import dev.aura.core.presentation.LogState
import dev.aura.core.presentation.Range
import dev.aura.core.presentation.SettingsState
import dev.aura.core.presentation.Store
import dev.aura.core.presentation.TrendsState
import java.time.LocalDate
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class Tab(val label: String) {
    DASHBOARD("Dashboard"),
    LOG("Log"),
    TRENDS("Trends"),
    COACH("Coach"),
    SETTINGS("Settings"),
}

data class ChatTurn(
    val fromUser: Boolean,
    val text: String,
    val grounding: Grounding? = null,
    val trace: Trace? = null,
    val retried: Boolean = false,
)

/**
 * Everything the screens read and write, held in one place.
 *
 * No queries or arithmetic live here either — it calls [Store] and keeps what
 * comes back. Its whole job is to move work off the main thread and to hold the
 * results, because a database read on the main thread is a dropped frame and,
 * with enough history, a visible stutter.
 */
class AuraState(
    private val database: AuraDatabase,
    private val storage: Storage,
    private val scope: CoroutineScope,
) {

    // Both are replaced wholesale by a restore, so neither can be a val: every
    // handle taken before the file was swapped is pointing at a dead database.
    private var db: Db = database.open()
    private var store = Store(db)

    private fun reopen() {
        runCatching { db.close() }
        db = database.open()
        store = Store(db)
        conversation = Conversation.EMPTY
    }

    var tab by mutableStateOf(Tab.DASHBOARD)
    var busy by mutableStateOf(false)
        private set

    var dashboard by mutableStateOf<DashboardState?>(null)
        private set
    var trends by mutableStateOf<TrendsState?>(null)
        private set
    var log by mutableStateOf<LogState?>(null)
        private set
    var settings by mutableStateOf<SettingsState?>(null)
        private set

    var range by mutableStateOf(Range.QUARTER)
        private set
    var chosenExercise by mutableStateOf<String?>(null)
        private set

    var chat by mutableStateOf(listOf<ChatTurn>())
        private set
    var chatError by mutableStateOf<String?>(null)
        private set
    private var conversation = Conversation.EMPTY

    var notice by mutableStateOf<String?>(null)

    // ----------------------------------------------------------------------

    private fun load(block: suspend () -> Unit) {
        scope.launch {
            busy = true
            try {
                block()
            } catch (e: Exception) {
                notice = e.message ?: e.toString()
            } finally {
                busy = false
            }
        }
    }

    private suspend fun <T> onIo(block: () -> T): T = withContext(Dispatchers.IO) { block() }

    fun refresh() = load {
        when (tab) {
            Tab.DASHBOARD -> dashboard = onIo { store.dashboard() }
            Tab.TRENDS -> trends = onIo { store.trends(range, chosenExercise) }
            Tab.LOG -> log = onIo { store.log() }
            Tab.SETTINGS -> settings = onIo { store.settings() }
            Tab.COACH -> Unit
        }
    }

    fun show(next: Tab) {
        tab = next
        refresh()
    }

    fun selectRange(next: Range) {
        range = next
        refresh()
    }

    fun chooseExercise(name: String) {
        chosenExercise = name
        refresh()
    }

    // ----------------------------------------------------------------------

    fun addSet(exercise: String, weightKg: Double?, reps: Int?, isWarmup: Boolean) = load {
        onIo { store.addSet(exercise, weightKg, reps, isWarmup) }
        log = onIo { store.log() }
    }

    /** Make a starter workout today's plan and go to where it is logged. */
    fun startWorkout(id: String) = load {
        onIo { store.startWorkout(id) }
        tab = Tab.LOG
        log = onIo { store.log() }
    }

    fun finishWorkout() = load {
        onIo { store.finishWorkout() }
        log = onIo { store.log() }
    }

    fun deleteSet(id: Int) = load {
        onIo { store.deleteSet(id) }
        log = onIo { store.log() }
    }

    fun saveGemini(apiKey: String?, model: String?) = load {
        onIo { Settings.saveGemini(db, apiKey, model) }
        settings = onIo { store.settings() }
        notice = "Saved."
    }

    fun clearApiKey() = load {
        onIo { Settings.clearApiKey(db) }
        settings = onIo { store.settings() }
    }

    fun saveWatchFolders(folders: List<String>) = load {
        onIo { Settings.saveWatchFolders(db, folders) }
        settings = onIo { store.settings() }
        notice = "Saved."
    }

    // ----------------------------------------------------------------------

    fun ask(message: String) {
        val question = message.trim()
        if (question.isEmpty()) return
        chat = chat + ChatTurn(fromUser = true, text = question)
        chatError = null

        load {
            val key = onIo { Settings.apiKey(db) }
            if (key.isNullOrBlank()) {
                chatError = "No Gemini API key yet. Add one in Settings."
                return@load
            }
            val model = onIo { Settings.model(db) }
            try {
                val answer =
                    onIo { Coach(db, apiKey = key, model = model).ask(question, conversation) }
                conversation = answer.conversation
                chat =
                    chat +
                        ChatTurn(
                            fromUser = false,
                            text = answer.text,
                            grounding = answer.grounding,
                            trace = answer.trace,
                            retried = answer.retried,
                        )
            } catch (e: CoachError) {
                chatError = e.message
            }
        }
    }

    // ----------------------------------------------------------------------
    // Files
    // ----------------------------------------------------------------------

    var folders by mutableStateOf(listOf<Pair<String, android.net.Uri>>())
        private set

    fun refreshFolders() {
        folders = storage.grantedFolders().map { storage.displayName(it) to it }
    }

    fun addFolder(tree: android.net.Uri) = load {
        onIo { storage.persist(tree) }
        refreshFolders()
        notice = "Added. Import now to read what is in it."
    }

    fun forgetFolder(tree: android.net.Uri) = load {
        onIo { storage.release(tree) }
        refreshFolders()
    }

    /**
     * Read every watched folder.
     *
     * Files are identified by content, so an unrelated file in a folder that
     * belongs to another app is skipped in silence rather than reported as a
     * failure — which is most of what is in those folders.
     */
    fun importNow() = load {
        val outcome =
            onIo {
                var imported = 0
                var written = 0
                var skipped = 0
                for (tree in storage.grantedFolders()) {
                    for (entry in storage.filesIn(tree)) {
                        val copy =
                            runCatching { storage.copyToCache(entry.uri, entry.name) }
                                .getOrNull() ?: continue
                        try {
                            storage.openReadOnly(copy).use { source ->
                                val result = Inbox.importFrom(source, db)
                                if (result.kind == FileKind.UNKNOWN) skipped++
                                else {
                                    imported++
                                    written += result.written
                                }
                            }
                        } catch (_: Exception) {
                            // A half-written backup will be whole next time.
                            skipped++
                        } finally {
                            copy.delete()
                        }
                    }
                }
                storage.clearCache()
                Triple(imported, written, skipped)
            }

        val (files, rows, skipped) = outcome
        notice =
            when {
                files == 0 && skipped == 0 -> "Nothing found. Is the right folder added?"
                files == 0 -> "Nothing to import; $skipped file(s) were not ours."
                else -> "Imported $rows record(s) from $files file(s)."
            }
        refresh()
    }

    /** Check a chosen file before offering to replace anything with it. */
    fun inspectBackup(uri: android.net.Uri, name: String) = load {
        pendingRestore = null
        val info = onIo {
            val copy = storage.copyToCache(uri, name)
            try {
                storage.openReadOnly(copy).use { Backup.verify(it) }
            } finally {
                copy.delete()
            }
        }
        pendingRestore = uri to info
    }

    var pendingRestore by mutableStateOf<Pair<android.net.Uri, Backup.Info>?>(null)
        private set

    fun cancelRestore() {
        pendingRestore = null
    }

    /** Replace everything with the chosen backup, having already verified it. */
    fun restore(uri: android.net.Uri, name: String) = load {
        onIo {
            val copy = storage.copyToCache(uri, name)
            try {
                // Verified again rather than trusting the earlier look: the
                // file is re-read here, and this is the irreversible step.
                storage.openReadOnly(copy).use { Backup.verify(it) }
                database.replaceWith(copy)
            } finally {
                copy.delete()
                storage.clearCache()
            }
        }
        reopen()
        pendingRestore = null
        notice = "Restored."
        refresh()
    }

    /** Write a consistent copy of the database to wherever the user chose. */
    fun exportBackup(uri: android.net.Uri) = load {
        val info = onIo {
            Backup.checkpoint(db)
            storage.writeTo(uri, database.file())
            Backup.describe(db)
        }
        notice =
            if (info.isEmpty) "Saved, though there is nothing in it yet."
            else "Saved ${info.workouts} workout(s) and ${info.sets} set(s)."
    }

    fun suggestedBackupName(): String = "aura-backup-${LocalDate.now()}.db"

    fun clearChat() {
        chat = emptyList()
        conversation = Conversation.EMPTY
        chatError = null
    }

    val today: LocalDate
        get() = LocalDate.now()
}
