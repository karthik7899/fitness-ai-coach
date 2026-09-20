plugins {
    alias(libs.plugins.kotlin.jvm)
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
    // No production dependencies. Anything added here has to be available on
    // Android too, so the bar is deliberately high.
    testImplementation(kotlin("test"))
    testImplementation(libs.sqlite.jdbc)
    testImplementation(platform(libs.junit.bom))
    testImplementation(libs.junit.jupiter)
    testRuntimeOnly(libs.junit.platform.launcher)
}

tasks.test {
    useJUnitPlatform()
    testLogging { events("failed") }
}
