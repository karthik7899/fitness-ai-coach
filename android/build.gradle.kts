// Deliberately declares no plugins.
//
// The obvious thing is to declare them here with `apply false` so each module
// can drop its version, and Gradle warns that you should. Doing it breaks the
// build in two ways that cancel each other out:
//
//   - Declaring the Kotlin plugin here loads it into the root's classloader,
//     where it cannot see the Android Gradle Plugin. Applying it in :app then
//     fails with NoClassDefFoundError on com/android/build/gradle/api/
//     BaseVariant. The two have to be declared together to share a classloader.
//
//   - But declaring AGP here makes it resolve for every build, including
//     :core:test — and AGP comes from Google's Maven. That breaks :core on any
//     machine that cannot reach it, which is the one property the module split
//     exists to protect.
//
// So the modules declare their own, and the "Kotlin plugin loaded multiple
// times" warning stands. It is a warning: the versions match, and each module
// loads the plugin alongside whatever else it needs.
