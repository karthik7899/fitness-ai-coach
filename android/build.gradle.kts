// The Kotlin plugin is declared once here and applied in the modules. Declaring
// it with a version in each module loads it twice, which Gradle warns about and
// does not support.
//
// The Android Gradle Plugin is deliberately absent: a plugin declared here has
// to resolve even with `apply false`, and AGP comes from Google's Maven. Naming
// it would make :core unbuildable on a machine that cannot reach it, which is
// exactly the property the module split exists to protect. :app declares it
// instead, and :app is only in the build when there is an SDK.
plugins {
    alias(libs.plugins.kotlin.jvm) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.serialization) apply false
    alias(libs.plugins.kotlin.compose) apply false
}
