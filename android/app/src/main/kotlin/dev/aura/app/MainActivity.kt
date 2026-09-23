package dev.aura.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import dev.aura.app.ui.AuraApp
import dev.aura.app.ui.AuraColors
import dev.aura.app.ui.AuraTheme

class MainActivity : ComponentActivity() {

    private val database by lazy { AuraDatabase(applicationContext) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            AuraTheme {
                val scope = rememberCoroutineScope()
                // Opened once and kept: SQLiteOpenHelper caches the handle, and
                // reopening it on every recomposition would be a slow mistake.
                val app = remember { AuraState(database, Storage(applicationContext), scope) }
                LaunchedEffect(Unit) {
                    app.refreshFolders()
                    app.refresh()
                }

                Surface(modifier = Modifier.fillMaxSize(), color = AuraColors.Background) {
                    AuraApp(app)
                }
            }
        }
    }
}
