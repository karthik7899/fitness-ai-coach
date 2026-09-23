plugins {
    alias(libs.plugins.kotlin.jvm)
    alias(libs.plugins.kotlin.serialization)
}

// Java 17 rather than a toolchain: a toolchain would try to download a JDK,
// and every JDK this builds on already satisfies 17.
java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    // The one production dependency. JSON is unavoidable here — the tool
    // schemas and the Gemini wire format are both JSON — and hand-rolling a
    // parser for a health app is a worse trade than one Kotlin-first library
    // that works identically on the JVM and on Android.
    implementation(libs.kotlinx.serialization.json)

    testImplementation(kotlin("test"))
    testImplementation(libs.sqlite.jdbc)
    testImplementation(platform(libs.junit.bom))
    testImplementation(libs.junit.jupiter)
    testRuntimeOnly(libs.junit.platform.launcher)
}

tasks.test {
    useJUnitPlatform()
    testLogging { events("failed") }
    // The import fixtures are shared with the Python suite and live outside
    // this build, at the repository root. So are the eval scenarios; see
    // EvalTest. Both are declared as inputs, or Gradle would call the tests
    // up to date after an edit to either and not run them.
    val fixtures = rootProject.file("../fixtures")
    val scenarios = rootProject.file("../evals/scenarios")
    inputs.dir(fixtures).withPathSensitivity(PathSensitivity.RELATIVE)
    inputs.dir(scenarios).withPathSensitivity(PathSensitivity.RELATIVE)
    systemProperty("aura.fixtures", fixtures.absolutePath)
    systemProperty("aura.evals", scenarios.absolutePath)
}
