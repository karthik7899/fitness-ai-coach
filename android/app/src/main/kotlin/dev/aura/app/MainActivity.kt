package dev.aura.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import dev.aura.core.DailyVolume
import dev.aura.core.Metrics
import dev.aura.core.Summary
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * The dashboard, and for now the whole app.
 *
 * It exists to prove the chain end to end on a device: the generated schema
 * opens, the views answer, and the numbers match the ones the tests pin down.
 * Logging, import and the coach follow once that is true on real hardware.
 */
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val database = AuraDatabase(applicationContext)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    DashboardScreen(metrics = Metrics(database.open()))
                }
            }
        }
    }
}

@Composable
fun DashboardScreen(metrics: Metrics) {
    var summary by remember { mutableStateOf<Summary?>(null) }

    LaunchedEffect(metrics) {
        summary = withContext(Dispatchers.IO) { metrics.summary() }
    }

    Column(
        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Aura", style = MaterialTheme.typography.headlineMedium)

        val current = summary
        if (current == null) {
            Text("Loading…", style = MaterialTheme.typography.bodyMedium)
        } else {
            Dashboard(current)
        }
    }
}

@Composable
private fun ColumnScope.Dashboard(summary: Summary) {
    val load = summary.load
    if (load != null) {
        Section("Training load")
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Stat("Acute (7d)", format(load.acute7d), Modifier.weight(1f))
            Stat("Chronic (28d)", format(load.chronic28d), Modifier.weight(1f))
            Stat("ACWR", load.acwr?.let { format(it) } ?: "—", Modifier.weight(1f))
        }
    }

    if (summary.latestMetrics.isNotEmpty()) {
        Section("Latest wellness")
        summary.latestMetrics.values.sortedBy { it.metric }.forEach {
            Stat(it.metric.replace('_', ' '), "${format(it.value)} ${it.unit.orEmpty()}".trim())
        }
    }

    Section("Recent sessions")
    if (summary.recentWorkouts.isEmpty()) {
        Text("Nothing logged yet.", style = MaterialTheme.typography.bodyMedium)
    } else {
        summary.recentWorkouts.forEach { WorkoutRow(it) }
    }
}

@Composable
private fun Section(title: String) {
    Text(title.uppercase(), style = MaterialTheme.typography.labelLarge)
}

@Composable
private fun Stat(label: String, value: String, modifier: Modifier = Modifier) {
    Card(modifier = modifier) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text(label, style = MaterialTheme.typography.labelMedium)
            Text(value, style = MaterialTheme.typography.headlineSmall)
        }
    }
}

@Composable
private fun WorkoutRow(day: DailyVolume) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(day.date.toString(), style = MaterialTheme.typography.bodyMedium)
            Text(
                "${format(day.volumeKg)} kg · ${day.workingSets} sets",
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

/** Trailing zeros on a training number read as false precision. */
private fun format(value: Double): String =
    if (value == value.toLong().toDouble()) value.toLong().toString() else "%.2f".format(value)
