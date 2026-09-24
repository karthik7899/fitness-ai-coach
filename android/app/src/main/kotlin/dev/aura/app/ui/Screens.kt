package dev.aura.app.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxHeight
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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import dev.aura.app.AuraState
import dev.aura.app.BuildConfig
import dev.aura.app.Tab
import dev.aura.app.ChatTurn
import dev.aura.core.Advice
import dev.aura.core.Plan
import dev.aura.core.PlanEntry
import dev.aura.core.Template
import dev.aura.core.agent.Grounding
import dev.aura.core.agent.Trace
import dev.aura.core.agent.TraceStep
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
fun DashboardScreen(state: DashboardState?, app: AuraState) {
    if (state == null) {
        Muted("Loading…")
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        if (state.templates.isNotEmpty()) {
            SectionTitle("Workouts by body part")
            for (template in state.templates) {
                TemplateCard(
                    template = template,
                    active = template.id == state.activeTemplate,
                    enabled = !app.busy,
                    onStart = { app.startWorkout(template.id) },
                )
            }
        }

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

@Composable
private fun TemplateCard(
    template: Template,
    active: Boolean,
    enabled: Boolean,
    onStart: () -> Unit,
) {
    Panel {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(template.name, color = AuraColors.Text, fontWeight = FontWeight.SemiBold)
                Text(
                    template.about,
                    color = AuraColors.Muted,
                    style = MaterialTheme.typography.labelMedium,
                )
            }
            TextButton(onClick = onStart, enabled = enabled) {
                Text(if (active) "Continue" else "Start", color = AuraColors.Accent)
            }
        }
        Text(
            template.exercises.joinToString(" · ") { "${it.exercise} ${it.sets}×${it.repsMin}–${it.repsMax}" },
            color = AuraColors.Muted,
            style = MaterialTheme.typography.labelMedium,
            modifier = Modifier.padding(top = 6.dp),
        )
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
    var rpe by remember { mutableStateOf<String?>(null) }

    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        RestTimer(app)

        state.plan?.let { plan ->
            PlanSection(
                plan = plan,
                selected = exercise,
                onChoose = { entry ->
                    exercise = entry.exercise
                    reps = entry.target.reps.toString()
                    // Today's target, else what was lifted last; plain digits,
                    // since this is parsed back, so no grouping or locale.
                    weight = (entry.target.weightKg ?: entry.lastWeightKg)
                        ?.let { java.math.BigDecimal.valueOf(it).stripTrailingZeros().toPlainString() }
                        .orEmpty()
                    warmup = false
                    rpe = null
                },
                onFinish = app::finishWorkout,
            )
        }

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

        // How hard the set was: RPE 10 is nothing left, 8 is two reps in reserve.
        // Optional, but it is what tells the progression rule a grind from an
        // easy set at the same numbers.
        Row(verticalAlignment = Alignment.CenterVertically) {
            Muted("RPE", modifier = Modifier.padding(end = 4.dp))
            ChipRow(
                options = listOf("6", "7", "8", "9", "10"),
                selected = rpe.orEmpty(),
                onSelect = { rpe = if (rpe == it) null else it },
            )
        }

        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Button(
                onClick = {
                    val rest =
                        if (warmup) 60
                        else state.plan?.entries
                            ?.firstOrNull { it.exercise.equals(exercise.trim(), true) }
                            ?.restS ?: 120
                    app.addSet(
                        exercise,
                        weight.toDoubleOrNull(),
                        reps.toIntOrNull(),
                        warmup,
                        rpe = rpe?.toDoubleOrNull(),
                        restSeconds = rest,
                    )
                    rpe = null
                    // Following a plan, the next set is usually the same again.
                    val planned = state.plan?.entries?.any { it.exercise.equals(exercise.trim(), true) }
                    if (planned != true) {
                        weight = ""
                        reps = ""
                    }
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
                                    entry.rpe?.let { append("  ·  RPE ${Format.number(it, 1)}") }
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

/**
 * Today's starter workout as a checklist. Tapping an exercise fills the form
 * below with it: the target reps and the weight used last time.
 */
@Composable
private fun PlanSection(
    plan: Plan,
    selected: String,
    onChoose: (PlanEntry) -> Unit,
    onFinish: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        SectionTitle(plan.template.name + if (plan.complete) " — done" else "")
        TextButton(onClick = onFinish) { Text("Finish", color = AuraColors.Muted) }
    }
    for (entry in plan.entries) {
        val chosen = entry.exercise.equals(selected.trim(), ignoreCase = true)
        Panel(modifier = Modifier.clickable { onChoose(entry) }) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        entry.exercise,
                        color = if (chosen) AuraColors.Accent else AuraColors.Text,
                        fontWeight = if (chosen) FontWeight.SemiBold else FontWeight.Normal,
                    )
                    Text(
                        buildString {
                            append("${entry.sets} × ${entry.repsMin}–${entry.repsMax}")
                            // Your own name for it, from an import, may differ from the plan's.
                            if (!entry.exercise.equals(entry.planned, ignoreCase = true)) {
                                append("  ·  for ${entry.planned}")
                            }
                            entry.lastWeightKg?.let { append("  ·  last ${Format.kg(it)}") }
                        },
                        color = AuraColors.Muted,
                        style = MaterialTheme.typography.labelMedium,
                    )
                    Text(
                        targetLine(entry),
                        color = if (entry.target.advice == Advice.UP) AuraColors.StatusGood else AuraColors.Text,
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
                // Stated in words as well as colour, which alone is not a label.
                Text(
                    if (entry.complete) "✓ ${entry.done}/${entry.sets}" else "${entry.done}/${entry.sets}",
                    color = if (entry.complete) AuraColors.StatusGood else AuraColors.Muted,
                    style = MaterialTheme.typography.labelLarge,
                )
            }
        }
    }
}

/** Today's target in words, with which way it moved and why. */
private fun targetLine(entry: PlanEntry): String {
    val t = entry.target
    val load = t.weightKg?.let { "${Format.kg(it)} × ${t.reps}" } ?: "${t.reps} reps"
    return when (t.advice) {
        Advice.NEW -> "Today: ${t.reps} reps, a weight you could lift ${entry.repsMax} times"
        Advice.UP ->
            if (t.weightKg == null) "Today: top of the range last time, add load"
            else "Today: $load  ↑ up from last time"
        Advice.REPEAT -> "Today: $load  ·  beat last time"
        Advice.DOWN -> "Today: $load  ↓ lighter, to get back in the range"
    }
}

/**
 * Counts down the rest after a set, then buzzes and beeps. In the app only:
 * with the screen off it waits, and the elapsed time still counts.
 */
@Composable
private fun RestTimer(app: AuraState) {
    val endsAt = app.restEndsAt ?: return
    var now by remember { mutableStateOf(android.os.SystemClock.elapsedRealtime()) }
    val haptics = LocalHapticFeedback.current

    LaunchedEffect(endsAt) {
        while (true) {
            now = android.os.SystemClock.elapsedRealtime()
            if (now >= endsAt) {
                haptics.performHapticFeedback(HapticFeedbackType.LongPress)
                runCatching {
                    val tone = android.media.ToneGenerator(android.media.AudioManager.STREAM_NOTIFICATION, 80)
                    tone.startTone(android.media.ToneGenerator.TONE_PROP_BEEP2, 400)
                    kotlinx.coroutines.delay(500)
                    tone.release()
                }
                app.endRest()
                break
            }
            kotlinx.coroutines.delay(250)
        }
    }

    val remaining = ((endsAt - now).coerceAtLeast(0) + 999) / 1000
    val fraction =
        if (app.restTotalMs <= 0) 0f
        else ((endsAt - now).coerceAtLeast(0).toFloat() / app.restTotalMs).coerceIn(0f, 1f)
    Panel {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "Rest  %d:%02d".format(java.util.Locale.ROOT, remaining / 60, remaining % 60),
                color = AuraColors.Text,
                style = MaterialTheme.typography.titleMedium,
            )
            Row {
                TextButton(onClick = { app.extendRest(30) }) { Text("+30s", color = AuraColors.Accent) }
                TextButton(onClick = app::endRest) { Text("Skip", color = AuraColors.Muted) }
            }
        }
        Box(
            modifier = Modifier.fillMaxWidth().height(4.dp).background(AuraColors.Border)
        ) {
            Box(Modifier.fillMaxWidth(fraction).fillMaxHeight().background(AuraColors.Accent))
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
    var showTrace by remember { mutableStateOf(false) }

    Panel {
        Text(
            if (turn.fromUser) "You" else "Coach",
            color = if (turn.fromUser) AuraColors.Muted else AuraColors.Accent,
            style = MaterialTheme.typography.labelMedium,
        )
        Text(turn.text, color = AuraColors.Text, modifier = Modifier.padding(top = 4.dp))

        turn.grounding?.let { Verdict(it, turn.retried) }

        val trace = turn.trace
        if (trace != null && trace.steps.isNotEmpty()) {
            TextButton(onClick = { showTrace = !showTrace }) {
                Text(
                    if (showTrace) "Hide how this was answered" else "How this was answered",
                    color = AuraColors.Muted,
                    style = MaterialTheme.typography.labelMedium,
                )
            }
            if (showTrace) TraceView(trace)
        }
    }
}

/**
 * Whether the answer's figures were found in the athlete's data.
 *
 * Worded as well as coloured — colour alone is not a label — and specific
 * about which figures failed, because "something may be wrong" is not
 * something anyone can act on.
 */
@Composable
private fun Verdict(grounding: Grounding, retried: Boolean) {
    val total = grounding.verified.size + grounding.unverified.size
    if (total == 0) return
    val (line, color) =
        if (grounding.ok) {
            val correction = if (retried) ", after one correction" else ""
            "✓ All $total figure${if (total == 1) "" else "s"} found in your data$correction" to
                AuraColors.StatusGood
        } else {
            "⚠ Not found in your data: ${grounding.unverified.joinToString(", ")}" to
                AuraColors.StatusWarning
        }
    Text(
        line,
        color = color,
        style = MaterialTheme.typography.labelMedium,
        modifier = Modifier.padding(top = 6.dp),
    )
}

@Composable
private fun TraceView(trace: Trace) {
    Column(modifier = Modifier.padding(top = 2.dp)) {
        for (step in trace.steps) {
            val kind =
                when (step.kind) {
                    TraceStep.Kind.MODEL -> "model"
                    TraceStep.Kind.TOOL -> "tool"
                    TraceStep.Kind.CHECK -> "check"
                    TraceStep.Kind.RETRY -> "retry"
                }
            val parts = listOf(kind, step.label, step.detail, duration(step.millis))
                .filter { it.isNotBlank() }
            Text(
                parts.joinToString(" · ") + if (step.failed) "  (failed)" else "",
                color = if (step.failed) AuraColors.StatusWarning else AuraColors.Muted,
                style = MaterialTheme.typography.labelMedium,
            )
        }
        val totals =
            buildList {
                add("${trace.modelCalls} model call${if (trace.modelCalls == 1) "" else "s"}")
                add("${trace.toolCalls} tool call${if (trace.toolCalls == 1) "" else "s"}")
                if (trace.usage.totalTokens > 0) add("${Format.number(trace.usage.totalTokens.toDouble())} tokens")
                add(duration(trace.totalMillis))
            }
        Text(
            totals.joinToString(" · "),
            color = AuraColors.Text,
            style = MaterialTheme.typography.labelMedium,
            modifier = Modifier.padding(top = 4.dp),
        )
    }
}

private fun duration(millis: Long): String =
    if (millis < 1000) "$millis ms" else Format.number(millis / 1000.0, 1) + " s"

// --------------------------------------------------------------------------

@Composable
fun SettingsScreen(state: SettingsState?, app: AuraState) {
    if (state == null) {
        Muted("Loading…")
        return
    }
    var apiKey by remember { mutableStateOf("") }
    var model by remember { mutableStateOf(state.model) }

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

        ImportSection(app)
        DuplicatesSection(state, app)
        BackupSection(app)

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

/**
 * Folders the app may read, chosen through the system picker.
 *
 * Picking a folder is the permission: there is no storage permission to grant,
 * and the app can see nothing it was not handed.
 */
@Composable
private fun ImportSection(app: AuraState) {
    val pickFolder =
        rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
            if (uri != null) app.addFolder(uri)
        }

    SectionTitle("Automatic import")
    Muted(
        "Choose the folders FitNotes and Gadgetbridge already back up to. They are " +
            "only ever read, and files that are not theirs are ignored."
    )

    if (app.folders.isEmpty()) {
        Muted("No folders yet.")
    } else {
        for ((name, uri) in app.folders) {
            Panel {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(name, color = AuraColors.Text)
                    TextButton(onClick = { app.forgetFolder(uri) }) {
                        Text("Forget", color = AuraColors.Muted)
                    }
                }
            }
        }
    }

    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Button(onClick = { pickFolder.launch(null) }, enabled = !app.busy) {
            Text("Add folder")
        }
        Button(onClick = { app.importNow() }, enabled = !app.busy && app.folders.isNotEmpty()) {
            Text(if (app.busy) "Reading…" else "Import now")
        }
    }
}

/**
 * Export and restore.
 *
 * Restore is two steps on purpose: the file is opened and described before
 * anything is replaced, because this is the one action in the app that can
 * destroy data.
 */
/**
 * Exercises that exist under more than one name, such as a "Bench Press" a
 * workout created beside an imported "Flat Barbell Bench Press". Each line
 * says where the sets go before anything moves.
 */
@Composable
private fun DuplicatesSection(state: SettingsState, app: AuraState) {
    SectionTitle("Duplicate exercises")
    if (state.duplicates.isEmpty()) {
        Muted("None. Every exercise has one name.")
        return
    }
    Muted(
        "These are the same exercise under different names. Merging moves the sets " +
            "onto the imported one and removes the other. It cannot be undone, so save " +
            "a backup first if in doubt."
    )
    Panel {
        for (merge in state.duplicates) {
            for (drop in merge.drop) {
                Text(
                    "${drop.name} (${setCount(drop.sets)}) → ${merge.keep.name} (${setCount(merge.keep.sets)})",
                    color = AuraColors.Text,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(vertical = 2.dp),
                )
            }
        }
    }
    Button(onClick = app::mergeDuplicates, enabled = !app.busy) {
        val count = state.duplicates.sumOf { it.drop.size }
        Text("Merge $count duplicate${if (count == 1) "" else "s"}")
    }
}

private fun setCount(n: Int) = "$n set${if (n == 1) "" else "s"}"

@Composable
private fun BackupSection(app: AuraState) {
    val save =
        rememberLauncherForActivityResult(
            ActivityResultContracts.CreateDocument("application/octet-stream")
        ) { uri ->
            if (uri != null) app.exportBackup(uri)
        }
    val pick =
        rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
            if (uri != null) app.inspectBackup(uri, "candidate.db")
        }

    SectionTitle("Backups")
    Muted(
        "Your whole history is one file. A backup is that file, so the desktop app " +
            "opens it too — it is the same schema."
    )

    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Button(onClick = { save.launch(app.suggestedBackupName()) }, enabled = !app.busy) {
            Text("Save a backup")
        }
        Button(onClick = { pick.launch(arrayOf("*/*")) }, enabled = !app.busy) {
            Text("Restore")
        }
    }

    val pending = app.pendingRestore
    if (pending != null) {
        val (uri, info) = pending
        Panel {
            Text(
                if (info.isEmpty) {
                    "That backup has no workouts in it."
                } else {
                    "${info.workouts} workouts, ${info.sets} sets" +
                        (info.earliest?.let { ", $it to ${info.latest}" } ?: "")
                },
                color = AuraColors.Text,
            )
            Text(
                "Restoring replaces everything currently in the app.",
                color = AuraColors.Muted,
                style = MaterialTheme.typography.labelMedium,
                modifier = Modifier.padding(top = 2.dp),
            )
            Row(
                modifier = Modifier.padding(top = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Button(onClick = { app.restore(uri, "candidate.db") }, enabled = !app.busy) {
                    Text("Replace my data")
                }
                TextButton(onClick = { app.cancelRestore() }) {
                    Text("Cancel", color = AuraColors.Muted)
                }
            }
        }
    }
}

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
            Tab.DASHBOARD -> DashboardScreen(app.dashboard, app)
            Tab.LOG -> LogScreen(app.log, app)
            Tab.TRENDS -> TrendsScreen(app.trends, app)
            Tab.COACH -> CoachScreen(app)
            Tab.SETTINGS -> SettingsScreen(app.settings, app)
        }
    }
}
