# Aura for Android

The native app, in two modules with a deliberate split:

```
core/   plain Kotlin. The schema, the metrics queries, the numbers.
        No Android imports, no Android SDK needed. Fully tested.
app/    Android. A SQLite handle, a Compose screen, and little else.
```

Everything that can be got wrong quietly — the SQL, the views, the unit
handling — lives in `core`, where it runs on any JVM and is covered by tests.
`app` is the part that needs a device, so it is kept as thin as it can be.

## Building

```bash
cd android
./gradlew :core:test      # works anywhere, no Android SDK required
```

For the app itself, open `android/` in Android Studio and press Run. The SDK
arrives with the IDE, and `local.properties` — which Studio writes on first
open — is what adds `:app` to the build. Without an SDK the build quietly
contains only `:core`, which is what makes the test command above portable.

From the command line, with an SDK already installed:

```bash
export ANDROID_HOME=~/Android/Sdk
./gradlew :app:assembleDebug        # build/outputs/apk/debug/app-debug.apk
./gradlew :app:installDebug         # to an attached device
```

## Where the schema comes from

`core/src/main/resources/aura/schema.sql` is **generated**, not written:

```bash
cd api && uv run python ../scripts/export_schema.py
```

It is the SQLite schema the Python migrations produce — the same tables, the
same seven metrics views. The phone and the server therefore compute every
number from one definition rather than two that drift apart. `api/tests/
test_schema_export.py` fails if the file falls behind the migrations, so the
drift is caught in CI rather than on a phone.

This is also why `core` has no production dependencies and no Room. Room would
mean declaring the schema a second time in annotations, which is precisely the
duplication the generated file exists to avoid. That trade is worth revisiting
once the app does more than read — but a second source of truth for the schema
should be a decision, not a default.

## State

`./gradlew :core:test` — 18 tests, passing. They run the real generated schema
and the real views under SQLite, and assert the same figures the Python suite
asserts: the guarded Epley estimate, warmup exclusion, muscle attribution and
its category fallback, rest days as real zeros, ACWR, and source precedence
when two devices report the same day.

**`:app` has never been compiled.** The environment this was written in cannot
reach Google's Maven repository, so the Android Gradle Plugin, AndroidX and
Compose could not be resolved, and no `android.jar` was available to compile
against. Expect the first build in Android Studio to need fixing — most likely
a dependency version or a Compose API signature. The logic it depends on is
tested; the glue around it is not.

Still to port: logging, the FitNotes and Gadgetbridge importers, and the coach.
