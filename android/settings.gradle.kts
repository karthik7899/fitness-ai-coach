pluginManagement {
    repositories {
        gradlePluginPortal()
        mavenCentral()
        google()
    }
}

dependencyResolutionManagement {
    repositories {
        mavenCentral()
        google()
    }
}

rootProject.name = "aura"

include(":core")

// :core is plain Kotlin — it holds the schema, the queries and the importers,
// and builds and tests with no Android SDK anywhere in sight. That is
// deliberate: the logic worth testing is testable on any machine, and on CI,
// without an emulator.
//
// :app needs the SDK and Google's Maven repository, so it joins the build only
// when an SDK is actually present. Android Studio writes local.properties on
// first open, so it is included there automatically.
val hasAndroidSdk =
    file("local.properties").exists() ||
        System.getenv("ANDROID_HOME") != null ||
        System.getenv("ANDROID_SDK_ROOT") != null

if (hasAndroidSdk) {
    include(":app")
} else {
    logger.lifecycle("No Android SDK found — building :core only. Open in Android Studio for :app.")
}
