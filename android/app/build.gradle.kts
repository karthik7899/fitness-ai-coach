plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

// Every build gets a distinct identity. A hardcoded version means the phone
// cannot tell you which APK it is running, which is exactly the question you
// ask when something works and you want to keep it.
val ciBuild: Int = (System.getenv("GITHUB_RUN_NUMBER") ?: "0").toIntOrNull() ?: 0
val commit: String = (System.getenv("GITHUB_SHA") ?: "").take(7).ifEmpty { "local" }

android {
    namespace = "dev.aura.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "dev.aura.app"
        minSdk = 26 // java.time without desugaring
        targetSdk = 35
        // versionCode must increase for an upgrade to install, so CI's run
        // number drives it. A local build stays at 1 and says "local".
        versionCode = if (ciBuild > 0) ciBuild else 1
        versionName = if (ciBuild > 0) "0.1.$ciBuild+$commit" else "0.1-local"
    }

    // buildConfig so the app can show its own version on the Settings screen;
    // digging through Android's app info to answer "which build is this" is a
    // poor substitute.
    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
}

kotlin {
    compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) }
}

dependencies {
    // The schema, the queries and the numbers all live here. This module is
    // the screen and the SQLite handle, and as little else as can be managed.
    implementation(project(":core"))

    implementation(libs.androidx.core.ktx)
    implementation(libs.coroutines.android)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.foundation)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.material3)
}
