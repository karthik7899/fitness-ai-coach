package dev.aura.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import dev.aura.app.AuraState
import dev.aura.app.BuildConfig
import dev.aura.app.Tab
import dev.aura.app.ChatTurn
import dev.aura.core.presentation.DashboardState
import dev.aura.core.presentation.Format
import dev.aura.core.presentation.LoadBand
import dev.aura.core.presentation.LogState
import dev.aura.core.presentation.Point
import dev.aura.core.presentation.Range
import dev.aura.core.presentation.Series
import dev.aura.core.presentation.SettingsState
import dev.aura.core.presentation.TrendsState

private fun bandColor(band: LoadBand): Color =
    when (band) {
        LoadBand.UNKNOWN -> AuraColors.Muted
        LoadBand.DETRAINING -> AuraColors.StatusWarning
        LoadBand.STEADY -> AuraColors.StatusGood
        LoadBand.STRETCHED -> AuraColors.StatusSerious
        LoadBand.SPIKE -> AuraColors.StatusCritical
    }

// --------------------------------------------------------------------------

@Composable
fun DashboardScreen(state: DashboardState?) {
    if (state == null) {
        Muted("Loading…")
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        if (state.wellness.isNotEmpty()) {
            SectionTitle("Latest wellness")
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                for (metric in state.wellness.take(2)) {
                    StatTile(
                        label = Format.metricName(metric.metric),
                        value = Format.metricValue(metric.metric, metric.value, metric.unit),
                        footnote = Format.day(metric.date),
                        modifier = Modifier.weight(1f),
                    )
                }
            }
        }

        SectionTitle("Training load")
        val load = state.load
        if (load == null) {
            Muted("Nothing logged yet.")
        } else {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                StatTile(
                    label = "Acute (7d)",
                    value = Format.number(load.acute7d),
                    modifier = Modifier.weight(1f),
                )
                StatTile(
                    label = "Chronic (28d)",
                    value = Format.number(load.chronic28d),
                    modifier = Modifier.weight(1f),
                )
                StatTile(
                    label = "ACWR",
                    value = Format.ratio(load.acwr),
                    // The band is stated as well as coloured: colour alone is
                    // not a label, and this is the number people misread.
                    footnote = state.band.label,
                    footnoteColor = bandColor(state.band),
                    modifier = Modifier.weight(1f),
                )
            }
        }

        SectionTitle("Recent sessions")
        if (state.recent.isEmpty()) {
            Muted("Nothing logged yet.")
        } else {
            for (day in state.recent) {
                Panel {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Text(Format.day(day.date), color = AuraColors.Text)
                        Text(
                            "${Format.compactKg(day.volumeKg)} · ${day.workingSets} sets",
                            color = AuraColors.Muted,
                        )
                    }
                }
            }
        }
    }
}

// --------------------------------------------------------------------------

@Composable
fun TrendsScreen(state: TrendsState?, app: AuraState) {
    if (state == null) {
        Muted("Loading…")
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        ChipRow(
            options = Range.entries.map { it.label },
            selected = app.range.label,
            onSelect = { label -> Range.entries.firstOrNull { it.label == label }?.let(app::selectRange) },
        )

        SectionTitle("Readiness")
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            StatTile(
                label = "Acute : chronic",
                value = Format.ratio(state.latest?.acwr),
                footnote = state.band.label,
                footnoteColor = bandColor(state.band),
                modifier = Modifier.weight(1f),
            )
            StatTile(
                label = "Acute load (7d)",
                value = Format.number(state.latest?.acute7d ?: 0.0),
                footnote = "arbitrary units",
                modifier = Modifier.weight(1f),
            )
        }

        SectionTitle("Acute vs chronic load")
        Panel {
            LineChart(
                series = listOf(state.acute, state.chronic),
                formatValue = { Format.number(it) },
            )
        }

        SectionTitle("Volume by muscle group")
        Panel {
            BarChart(
                bars = state.byMuscle.map { Bar(it.muscle, it.volumeKg) },
                formatValue = { Format.compactKg(it) },
            )
        }

        SectionTitle("Estimated 1RM")
        if (state.exercises.isEmpty()) {
            Muted("Log some sets and this fills in.")
        } else {
            ChipRow(
                options = state.exercises.take(6).map { it.exercise },
                selected = state.progressionFor.orEmpty(),
                onSelect = app::chooseExercise,
            )
            Panel {
                val points =
                    state.progression.mapNotNull { day ->
                        day.bestE1rmKg?.let { Point(day.date, it) }
                    }
                LineChart(
                    // One series, so no legend: the section title names it.
                    series = listOf(Series(state.progressionFor.orEmpty(), points)),
                    formatValue = { Format.kg(it) },
                )
            }
        }
    }
}

// --------------------------------------------------------------------------

@Composable
fun LogScreen(state: LogState?, app: AuraState) {
    if (state == null) {
        Muted("Loading…")
        return
    }
    var exercise by remember { mutableStateOf("") }
    var weight by remember { mutableStateOf("") }
    var reps by remember { mutableStateOf("") }
    var warmup by remember { mutableStateOf(false) }

    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        SectionTitle("Log a set — ${Format.day(state.day)}")

        OutlinedTextField(
            value = exercise,
            onValueChange = { exercise = it },
            label = { Text("Exercise") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )

        if (state.recentExercises.isNotEmpty() && exercise.isBlank()) {
            ChipRow(
                options = state.recentExercises.take(6),
                selected = "",
                onSelect = { exercise = it },
            )
        }

        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedTextField(
                value = weight,
                onValueChange = { weight = it },
                label = { Text("kg") },
                singleLine = true,
                keyboardOptions =
                    androidx.compose.foundation.text.KeyboardOptions(
                        keyboardType = KeyboardType.Decimal
                    ),
                modifier = Modifier.weight(1f),
            )
            OutlinedTextField(
                value = reps,
                onValueChange = { reps = it },
                label = { Text("Reps") },
                singleLine = true,
                keyboardOptions =
                    androidx.compose.foundation.text.KeyboardOptions(
                        keyboardType = KeyboardType.Number
                    ),
                modifier = Modifier.weight(1f),
            )
        }

        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Button(
                onClick = {
                    app.addSet(exercise, weight.toDoubleOrNull(), reps.toIntOrNull(), warmup)
                    weight = ""
                    reps = ""
                },
                enabled = exercise.isNotBlank() && !app.busy,
            ) {
                Text("Add set")
            }
            TextButton(onClick = { warmup = !warmup }) {
                Text(
                    if (warmup) "Warmup ✓" else "Warmup",
                    color = if (warmup) AuraColors.Accent else AuraColors.Muted,
                )
            }
        }

        SectionTitle("Today")
        if (state.sets.isEmpty()) {
            Muted("Nothing logged yet today.")
        } else {
            for (entry in state.sets) {
                Panel {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column {
                            Text(entry.exercise, color = AuraColors.Text)
                            Text(
                                buildString {
                                    append(entry.weightKg?.let { Format.kg(it) } ?: "bodyweight")
                                    entry.reps?.let { append(" × $it") }
                                    if (entry.isWarmup) append("  ·  warmup")
                                },
                                color = AuraColors.Muted,
                                style = MaterialTheme.typography.labelMedium,
                            )
                        }
                        TextButton(onClick = { app.deleteSet(entry.id) }) {
                            Text("Remove", color = AuraColors.Muted)
                        }
                    }
                }
            }
        }
    }
}

// --------------------------------------------------------------------------

@Composable
fun CoachScreen(app: AuraState) {
    var draft by remember { mutableStateOf("") }

    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        SectionTitle("Coach")
        Muted(
            "Every number it quotes comes from your own data. Ask about readiness, " +
                "volume, a lift, or what to do next."
        )

        for (turn in app.chat) {
            ChatBubble(turn)
        }

        if (app.busy) Muted("Thinking…")
        app.chatError?.let { Text(it, color = AuraColors.Error) }

        Spacer(modifier = Modifier.height(4.dp))

        OutlinedTextField(
            value = draft,
            onValueChange = { draft = it },
            label = { Text("Ask the coach") },
            modifier = Modifier.fillMaxWidth(),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Button(
                onClick = {
                    app.ask(draft)
                    draft = ""
                },
                enabled = draft.isNotBlank() && !app.busy,
            ) {
                Text("Send")
            }
            if (app.chat.isNotEmpty()) {
                TextButton(onClick = { app.clearChat() }) {
                    Text("New conversation", color = AuraColors.Muted)
                }
            }
        }
    }
}

@Composable
private fun ChatBubble(turn: ChatTurn) {
    Panel {
        Text(
            if (turn.fromUser) "You" else "Coach",
            color = if (turn.fromUser) AuraColors.Muted else AuraColors.Accent,
            style = MaterialTheme.typography.labelMedium,
        )
        Text(turn.text, color = AuraColors.Text, modifier = Modifier.padding(top = 4.dp))
        if (turn.toolsUsed.isNotEmpty()) {
            // Worth showing: it is the difference between an answer read out of
            // the database and one the model made up.
            Text(
                "read ${turn.toolsUsed.joinToString(", ")}",
                color = AuraColors.Muted,
                style = MaterialTheme.typography.labelMedium,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}

// --------------------------------------------------------------------------

@Composable
fun SettingsScreen(state: SettingsState?, app: AuraState) {
    if (state == null) {
        Muted("Loading…")
        return
    }
    var apiKey by remember { mutableStateOf("") }
    var model by remember { mutableStateOf(state.model) }
    var folders by remember { mutableStateOf(state.watchFolders.joinToString("\n")) }

    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        SectionTitle("Coach")
        Muted(
            "The coach needs a Gemini API key, free from aistudio.google.com/apikey. " +
                "It is kept in your own database and sent nowhere but Google."
        )
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            StatTile(
                label = "API key",
                value = state.apiKeyHint ?: "Not set",
                modifier = Modifier.weight(1f),
            )
            StatTile(label = "Model", value = state.model, modifier = Modifier.weight(1f))
        }

        OutlinedTextField(
            value = apiKey,
            onValueChange = { apiKey = it },
            label = { Text(if (state.apiKeyHint != null) "Replace key" else "API key") },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = model,
            onValueChange = { model = it },
            label = { Text("Model") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Button(
                onClick = {
                    app.saveGemini(apiKey.ifBlank { null }, model.ifBlank { null })
                    apiKey = ""
                },
                enabled = !app.busy && (apiKey.isNotBlank() || model != state.model),
            ) {
                Text("Save")
            }
            if (state.apiKeyHint != null) {
                TextButton(onClick = { app.clearApiKey() }) {
                    Text("Remove key", color = AuraColors.Muted)
                }
            }
        }

        SectionTitle("Automatic import")
        Muted(
            "Point these at the folders FitNotes and Gadgetbridge already back up to. " +
                "They are only ever read."
        )
        OutlinedTextField(
            value = folders,
            onValueChange = { folders = it },
            label = { Text("One folder per line") },
            modifier = Modifier.fillMaxWidth(),
        )
        Button(onClick = { app.saveWatchFolders(folders.lines()) }, enabled = !app.busy) {
            Text("Save folders")
        }

        SectionTitle("This build")
        Panel {
            // The version name carries the commit it was built from, which is
            // what identifies a build when reporting that something broke.
            Text(BuildConfig.VERSION_NAME, color = AuraColors.Text)
            Text(
                "build ${BuildConfig.VERSION_CODE}",
                color = AuraColors.Muted,
                style = MaterialTheme.typography.labelMedium,
                modifier = Modifier.padding(top = 2.dp),
            )
        }

        SectionTitle("Database")
        Panel {
            val info = state.database
            Text(
                if (info.isEmpty) {
                    "Nothing stored yet."
                } else {
                    "${info.workouts} workouts, ${info.sets} sets, " +
                        "${info.exercises} exercises, ${info.dailyMetrics} daily readings."
                },
                color = AuraColors.Text,
            )
            if (info.earliest != null) {
                Text(
                    "${info.earliest} to ${info.latest}",
                    color = AuraColors.Muted,
                    style = MaterialTheme.typography.labelMedium,
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
        }

        SectionTitle("Privacy")
        Muted(
            "On Google's free tier, prompts and responses may be used to improve their " +
                "products, including human review. The coach's prompts carry your training " +
                "history, sleep and any injuries you mention. A paid key excludes your data."
        )
        Spacer(modifier = Modifier.height(16.dp))
    }
}

// --------------------------------------------------------------------------

@Composable
fun AuraApp(app: AuraState) {
    Column(
        modifier =
            Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text("Aura", color = AuraColors.Text, style = MaterialTheme.typography.headlineMedium)

        ChipRow(
            options = Tab.entries.map { it.label },
            selected = app.tab.label,
            onSelect = { label ->
                Tab.entries.firstOrNull { it.label == label }?.let(app::show)
            },
        )

        app.notice?.let { message ->
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(message, color = AuraColors.Muted)
                TextButton(onClick = { app.notice = null }) {
                    Text("dismiss", color = AuraColors.Muted)
                }
            }
        }

        when (app.tab) {
            Tab.DASHBOARD -> DashboardScreen(app.dashboard)
            Tab.LOG -> LogScreen(app.log, app)
            Tab.TRENDS -> TrendsScreen(app.trends, app)
            Tab.COACH -> CoachScreen(app)
            Tab.SETTINGS -> SettingsScreen(app.settings, app)
        }
    }
}
