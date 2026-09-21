package dev.aura.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun SectionTitle(text: String, modifier: Modifier = Modifier) {
    Text(
        text = text.uppercase(),
        color = AuraColors.Muted,
        fontWeight = FontWeight.SemiBold,
        letterSpacing = 1.sp,
        style = MaterialTheme.typography.labelLarge,
        modifier = modifier.padding(top = 8.dp, bottom = 4.dp),
    )
}

@Composable
fun Muted(text: String, modifier: Modifier = Modifier) {
    Text(
        text = text,
        color = AuraColors.Muted,
        style = MaterialTheme.typography.bodyMedium,
        modifier = modifier,
    )
}

/**
 * A single number with its name.
 *
 * A hero number rather than a chart, because one value over time that you
 * already know the trend of does not need a plot beside it.
 */
@Composable
fun StatTile(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    footnote: String? = null,
    footnoteColor: Color = AuraColors.Muted,
) {
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(containerColor = AuraColors.Panel),
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text(label, color = AuraColors.Muted, style = MaterialTheme.typography.labelMedium)
            Text(
                value,
                color = AuraColors.Text,
                style = MaterialTheme.typography.headlineSmall,
                modifier = Modifier.padding(top = 2.dp),
            )
            if (footnote != null) {
                Text(
                    footnote,
                    color = footnoteColor,
                    style = MaterialTheme.typography.labelMedium,
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
        }
    }
}

@Composable
fun Panel(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = AuraColors.Panel),
    ) {
        Column(modifier = Modifier.padding(12.dp)) { content() }
    }
}

/** A row of choices. Text rather than icons — these are words, not concepts. */
@Composable
fun ChipRow(
    options: List<String>,
    selected: String,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        for (option in options) {
            val active = option == selected
            Text(
                text = option,
                color = if (active) AuraColors.Text else AuraColors.Muted,
                style = MaterialTheme.typography.labelLarge,
                modifier =
                    Modifier.clip(RoundedCornerShape(999.dp))
                        .background(if (active) AuraColors.Border else Color.Transparent)
                        .clickable { onSelect(option) }
                        .padding(horizontal = 12.dp, vertical = 6.dp),
            )
        }
    }
}
