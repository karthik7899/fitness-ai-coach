package dev.aura.app.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/**
 * The same palette as the web app, so the two read as one product.
 *
 * Dark only, deliberately rather than by default: this is a thing you open in a
 * gym, often at the end of the day, and a white screen there is hostile. The
 * series pair was validated for colour-vision separation against this surface
 * (ΔE 26.8 protan, 31.8 normal), not chosen by eye.
 */
object AuraColors {
    val Background = Color(0xFF0F1115)
    val Panel = Color(0xFF171A21)
    val Border = Color(0xFF262B36)
    val Text = Color(0xFFE6E8EC)
    val Muted = Color(0xFF8B93A3)
    val Accent = Color(0xFF5B9CFF)
    val Error = Color(0xFFFF6B6B)

    /** Categorical series, in fixed order. Never cycled, never reassigned by rank. */
    val Series1 = Color(0xFF3987E5)
    val Series2 = Color(0xFFD95926)

    val Grid = Color(0xFF232834)

    val StatusGood = Color(0xFF0CA30C)
    val StatusWarning = Color(0xFFFAB219)
    val StatusSerious = Color(0xFFEC835A)
    val StatusCritical = Color(0xFFD03B3B)
}

private val AuraScheme =
    darkColorScheme(
        primary = AuraColors.Accent,
        onPrimary = Color(0xFF08121F),
        background = AuraColors.Background,
        onBackground = AuraColors.Text,
        surface = AuraColors.Panel,
        onSurface = AuraColors.Text,
        surfaceVariant = AuraColors.Panel,
        onSurfaceVariant = AuraColors.Muted,
        outline = AuraColors.Border,
        error = AuraColors.Error,
    )

@Composable
fun AuraTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = AuraScheme, content = content)
}
