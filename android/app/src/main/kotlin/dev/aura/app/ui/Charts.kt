package dev.aura.app.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import dev.aura.core.presentation.Point
import dev.aura.core.presentation.Series

/**
 * The charts.
 *
 * Deliberately few and deliberately plain. Every value is drawn from a SQL view
 * — nothing is computed here — and the rules the drawing follows are the ones
 * that keep a chart honest: one y axis, colour assigned to a series and never
 * to its rank, a legend whenever there is more than one series, and labels on
 * the ends rather than on every point.
 *
 * No text is drawn inside a Canvas. Axis and value labels are ordinary
 * composables laid out around it, which keeps them selectable, scalable with
 * the system font size, and legible to a screen reader.
 */

/** Series colours, in fixed order. The nth series is never a generated hue. */
private val SeriesColors = listOf(AuraColors.Series1, AuraColors.Series2)

@Composable
private fun LegendEntry(label: String, color: Color) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(modifier = Modifier.size(10.dp).clip(RoundedCornerShape(2.dp)).background(color))
        Spacer(modifier = Modifier.width(6.dp))
        // The label wears text ink, not the series colour: the swatch carries
        // identity, and coloured text is harder to read at this size.
        Text(label, color = AuraColors.Muted, style = MaterialTheme.typography.labelMedium)
    }
}

/**
 * One or two lines over a shared x axis.
 *
 * Two measures of different scale would need two charts; these share units
 * (arbitrary load), so they share an axis. There is never a second y scale.
 */
@Composable
fun LineChart(
    series: List<Series>,
    modifier: Modifier = Modifier,
    height: androidx.compose.ui.unit.Dp = 160.dp,
    formatValue: (Double) -> String = { it.toString() },
) {
    val drawable = series.filter { it.points.isNotEmpty() }
    if (drawable.isEmpty()) {
        Muted("Nothing to plot yet.")
        return
    }

    val allValues = drawable.flatMap { line -> line.points.map { it.value } }
    val maxValue = (allValues.maxOrNull() ?: 0.0).coerceAtLeast(0.0001)
    val pointCount = drawable.maxOf { it.points.size }

    Column(modifier = modifier.fillMaxWidth()) {
        if (drawable.size > 1) {
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                drawable.forEachIndexed { index, line ->
                    LegendEntry(line.label, SeriesColors[index % SeriesColors.size])
                }
            }
            Spacer(modifier = Modifier.height(8.dp))
        }

        Canvas(modifier = Modifier.fillMaxWidth().height(height)) {
            // A baseline, so a flat line at zero is visibly at zero.
            drawLine(
                color = AuraColors.Grid,
                start = Offset(0f, size.height),
                end = Offset(size.width, size.height),
                strokeWidth = 1f,
            )

            drawable.forEachIndexed { index, line ->
                val color = SeriesColors[index % SeriesColors.size]
                val step = if (pointCount > 1) size.width / (pointCount - 1) else 0f
                val path = Path()

                line.points.forEachIndexed { i, point ->
                    val x = step * i
                    val y = size.height - (point.value / maxValue * size.height).toFloat()
                    if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
                }

                drawPath(
                    path = path,
                    color = color,
                    style = Stroke(width = 2.dp.toPx(), cap = StrokeCap.Round),
                )

                // The most recent value gets a marker; the rest stay unlabelled.
                val last = line.points.lastOrNull()
                if (last != null) {
                    val x = step * (line.points.size - 1)
                    val y = size.height - (last.value / maxValue * size.height).toFloat()
                    drawCircle(color = color, radius = 4.dp.toPx(), center = Offset(x, y))
                }
            }
        }

        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Muted(drawable.first().points.first().date.toString())
            Muted(drawable.first().points.last().date.toString())
        }

        // Direct labels for the latest value of each line, instead of a tooltip:
        // there is no hover on a phone, and a number per point is unreadable.
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 2.dp),
            horizontalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            drawable.forEach { line ->
                val last = line.points.lastOrNull() ?: return@forEach
                Text(
                    text = "${line.label}: ${formatValue(last.value)}",
                    color = AuraColors.Text,
                    style = MaterialTheme.typography.labelMedium,
                )
            }
        }
    }
}

/** One labelled bar. */
data class Bar(val label: String, val value: Double)

/**
 * Horizontal bars for magnitude.
 *
 * All one colour on purpose: identity is carried by the labels beside them, so
 * a different hue per bar would be decoration pretending to be information.
 * Bars are anchored to a common baseline and read top-down, largest first.
 */
@Composable
fun BarChart(
    bars: List<Bar>,
    modifier: Modifier = Modifier,
    color: Color = AuraColors.Series1,
    formatValue: (Double) -> String = { it.toString() },
) {
    if (bars.isEmpty()) {
        Muted("Nothing to plot yet.")
        return
    }
    val maxValue = bars.maxOf { it.value }.coerceAtLeast(0.0001)

    Column(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        for (bar in bars) {
            Column {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(
                        bar.label,
                        color = AuraColors.Text,
                        style = MaterialTheme.typography.labelMedium,
                    )
                    Text(
                        formatValue(bar.value),
                        color = AuraColors.Muted,
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
                Box(
                    modifier =
                        Modifier.fillMaxWidth()
                            .height(8.dp)
                            .clip(RoundedCornerShape(4.dp))
                            .background(AuraColors.Grid)
                ) {
                    Box(
                        modifier =
                            Modifier.fillMaxWidth((bar.value / maxValue).toFloat())
                                .height(8.dp)
                                .clip(RoundedCornerShape(4.dp))
                                .background(color)
                    )
                }
            }
        }
    }
}

/** A line with no axis furniture, for showing shape beside a number. */
@Composable
fun Sparkline(
    points: List<Point>,
    modifier: Modifier = Modifier,
    color: Color = AuraColors.Series1,
) {
    if (points.size < 2) return
    val maxValue = points.maxOf { it.value }.coerceAtLeast(0.0001)

    Canvas(modifier = modifier.fillMaxWidth().height(40.dp)) {
        val step = size.width / (points.size - 1)
        val path = Path()
        points.forEachIndexed { i, point ->
            val x = step * i
            val y = size.height - (point.value / maxValue * size.height).toFloat()
            if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }
        drawPath(path, color, style = Stroke(width = 2.dp.toPx(), cap = StrokeCap.Round))
    }
}
