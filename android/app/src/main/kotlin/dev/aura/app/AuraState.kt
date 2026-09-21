package dev.aura.app

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import dev.aura.core.Db
import dev.aura.core.Settings
import dev.aura.core.agent.Coach
import dev.aura.core.agent.CoachError
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
import kotlinx.serialization.json.JsonObject

enum class Tab(val label: String) {
    DASHBOARD("Dashboard"),
    LOG("Log"),
    TRENDS("Trends"),
    COACH("Coach"),
    SETTINGS("Settings"),
}

data class ChatTurn(val fromUser: Boolean, val text: String, val toolsUsed: List<String> = emptyList())

/**
 * Everything the screens read and write, held in one place.
 *
 * No queries or arithmetic live here either — it calls [Store] and keeps what
 * comes back. Its whole job is to move work off the main thread and to hold the
 * results, because a database read on the main thread is a dropped frame and,
 * with enough history, a visible stutter.
 */
class AuraState(private val db: Db, private val scope: CoroutineScope) {

    private val store = Store(db)

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
    private var history = listOf<JsonObject>()

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
                    onIo { Coach(db, apiKey = key, model = model).ask(question, history) }
                history = answer.history
                chat =
                    chat +
                        ChatTurn(
                            fromUser = false,
                            text = answer.text,
                            toolsUsed = answer.toolCalls.map { it.name }.distinct(),
                        )
            } catch (e: CoachError) {
                chatError = e.message
            }
        }
    }

    fun clearChat() {
        chat = emptyList()
        history = emptyList()
        chatError = null
    }

    val today: LocalDate
        get() = LocalDate.now()
}
