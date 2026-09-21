# Aura

A personal training data warehouse with a coaching agent on top. Single user,
local-first: everything runs on your machine, and the only things that leave it
are the coach's calls to Gemini and whatever you choose to sync from Strava.
Watch and strength data never need to touch a cloud account at all.

The design principle is that **the database is the product**. Ingestion adapters,
the metrics layer, the web UI and the coach are all clients of one canonical
schema.

## Architecture

```
  Strava ────────┐
  FitNotes ──────┤
   backup folder ├─► adapters ─► raw_records ─► canonical ─► SQL views ─┐
  Gadgetbridge ──┤   (fetch,     (append-only)   tables     (e1RM, ACWR, │
   export folder │    normalise,                 (SI units)  volume)     │
  Health Connect ┘    upsert)                                            │
                                                                         ▼
  Log UI ──────────────────────────────────────────────────►  coach agent
                                                              (tool calls)
```

**1. Raw store.** Every adapter writes the upstream payload to `raw_records`
before normalising it. Nothing deletes from that table, so the canonical tables
can be rebuilt from it without re-contacting an API.

**2. Canonical model.** Source-agnostic tables in SI units — kilograms, metres,
seconds. No row carries its own unit; conversion happens at the display edge.
`daily_metrics` is long-form `(date, metric, source, value)`, so adding HRV or
SpO2 later is an insert rather than a migration.

**3. Derived metrics.** SQL views compute estimated 1RM (Epley, guarded to 1–12
reps), volume and working sets per muscle group, and training load with acute
(7-day) and chronic (28-day) averages plus their ratio. Rest days come from a
generated date spine, so a zero is a real zero.

**4. Coach agent.** Gemini with a typed tool surface over those views. The model
never does arithmetic — every figure it quotes comes from a tool call. It can
also write: `log_set` records a set from chat, and `remember` persists durable
facts (injuries, goals, constraints) that load into every later conversation.

The tool specs in `agent/tools.py` are plain JSON Schema and carry no provider
types; only `agent/coach.py` knows about Gemini, so swapping providers is one
file.

**5. Two databases, one schema.** On a phone the database is SQLite — a file the
server opens, with no daemon to keep alive, which removes the most fragile part
of an Android install. On a desktop it is PostgreSQL. The migrations, the seven
views and every write are portable across both, and the whole test suite runs
against each, so the numbers are the same wherever the app happens to be. Point
`DATABASE_URL` at either; `setup.sh` picks the right one for the machine.

Get a free key at [aistudio.google.com/apikey][key] and paste it into the
**Settings** tab — it is stored in the database and checked against the API on
save, so a bad key fails there rather than at chat time. `GEMINI_API_KEY` in
`.env` still works for headless setup; a key entered in the UI takes precedence,
and Settings always shows which of the two is in use. The key is never sent back
to the browser, only its last four characters.

Note that on Google's free tier prompts and responses may be used to improve
their products, including human review. This app's prompts carry your training
history, sleep and injuries; a paid key excludes that data from training.

[key]: https://aistudio.google.com/apikey

## Setup

```bash
./scripts/setup.sh     # database, schema, exercise catalogue, frontend build
./scripts/start.sh     # http://127.0.0.1:8000
```

That is the whole install, on a desktop or on a phone — the script detects which
and adjusts. FastAPI serves the built frontend, so the app is one process on one
port. No `.env` is required: add the API key and the import folders in the
**Settings** tab.

`setup.sh` is safe to re-run; it skips anything already done.

<details>
<summary>What the script does, if you would rather do it by hand</summary>

```bash
cd api
uv sync                                       # SQLite; nothing else to install
uv run alembic upgrade head
uv run python -m app.seed                     # ~35 exercises with muscle mappings
cd ../web && npm install && npm run build
cd ../api && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

That runs on SQLite, at `data/aura.db` by default. For PostgreSQL instead,
start one (`docker compose up -d`), set `DATABASE_URL` in `.env`, and install
the driver: `uv sync --extra binary`. psycopg needs libpq — the `binary` extra
bundles it, which is easiest everywhere except Termux, whose Bionic libc cannot
load manylinux wheels; there `--extra system` links against Termux's own
`postgresql` package instead.

</details>

For frontend work, run `npm run dev` alongside instead of building; Vite serves
on :5173 with hot reload and proxies the API.

## Data sources

**Strength** can be logged in the app directly, or kept in FitNotes and imported.
Both the `.fitnotes` SQLite backup and the CSV export work. Imported days land
under `source='fitnotes_import'`, separate from anything logged in the app, and
re-running replaces each imported day rather than duplicating it. Weights are
normalised to kilograms on the way in.

There is also a CLI, useful for a one-off backfill or for checking the mapping
against a real backup before trusting it:

```bash
uv run python -m app.adapters.fitnotes --inspect ~/Downloads/FitNotes_Backup.fitnotes
uv run python -m app.adapters.fitnotes ~/Downloads/FitNotes_Backup.fitnotes
```

**Strava** connects at `/api/sync/strava/authorize`, then `POST /api/sync/strava`
pulls activities incrementally from the newest one already stored.

**Watch folders** make import hands-off. Both FitNotes and Gadgetbridge can back
themselves up automatically to a folder; point the app at those folders in the
**Settings** tab and nothing else is ever needed — no export step, no copying, no
cloud account.

- **FitNotes** → Settings → Backup → automatic backup, and note the folder.
- **Gadgetbridge** → Settings → Auto export → enabled, and note the folder.

Watched folders are read and never written. Moving a backup out from under the
app that made it would be destructive, so files stay exactly where they are, and
unrelated files in those folders are ignored silently. Automatic backups
overwrite the same filename with fresh contents, which is the case hashing
handles: same name, new hash, re-imported — and the FitNotes importer replaces a
day rather than duplicating it.

**The inbox** is the manual path, for a one-off backup or a file from another
device. Drop it into `data/inbox/` and the scheduler imports it within two
minutes:

| File | Becomes |
| :--- | :--- |
| FitNotes `.fitnotes` backup | strength history |
| FitNotes CSV export | strength history |
| Gadgetbridge export (`.db`) | steps, resting HR, sleep |
| Health Connect export (`.zip`) | steps, sleep, HR, HRV, bodyweight |

Files are identified by probing their contents, not their extension, imported
once (keyed on the file's hash, so re-dropping a backup is a no-op), then moved
to `processed/`. Anything unrecognised goes to `rejected/` rather than being
retried forever. Sync the folder from your phone with Syncthing, or copy it over
USB — the app only ever reads local directories.

**Watch data without Google.** The Da Fit app has no export at all, so the way to
get your watch data out is to stop using it. [Gadgetbridge][gb] speaks the
Moyoung/CRRepa protocol these watches use, talks to the watch directly over
Bluetooth, and needs no account: pair the watch there, turn on Auto export, and
point a watch folder at it. Nothing touches Moyoung's servers or Google's.

Gadgetbridge stores samples in per-device tables whose shape depends on what you
have paired, so extraction is schema-discovering. Sleep is deliberately
conservative — Gadgetbridge keeps a device-specific raw kind and normalises it
only on read, so sleep is emitted only where the export carries an explicitly
typed sleep column. `inspect_export()` reports what a real export contains.

**Health Connect** stays supported for anyone who wants it. Google Fit's REST API
is not an option for a new build — signups closed in May 2024 and the APIs shut
down at the end of 2026, with [no replacement][fit-faq] — but Health Connect can
export on a schedule to Google Drive, and `POST /api/sync/health-connect` polls
for it. Or drop that ZIP in the inbox and skip the OAuth entirely.

[gb]: https://gadgetbridge.org/gadgets/wearables/moyoung/
[fit-faq]: https://developer.android.com/health-and-fitness/health-connect/migration/fit/faq

## Layout

```
api/
  app/
    models.py          canonical schema
    db.py              engine setup, including SQLite's corrected defaults
    views_sql.py       the seven metrics views, one definition per dialect
    upsert.py          dialect-aware ON CONFLICT
    queries.py         shared SQL row helpers
    scheduler.py       interval sync, started by the app lifespan
    settings_store.py  UI settings layered over .env
    adapters/          inbox, fitnotes, gadgetbridge, strava, health_connect
    agent/             tool definitions + the coaching loop
    routers/           training, metrics, coach (SSE), sync, settings
  alembic/versions/    0001 tables, 0002 views, 0003 settings, 0004 portability
scripts/               setup.sh, start.sh, export_schema.py
android/
  core/                plain Kotlin: schema, metrics queries, tests
  app/                 Android: SQLite handle and Compose UI
web/
  src/charts/          LineChart, BarChart, scales and formatting
  src/pages/           Dashboard, Log, Trends, Coach, Settings
```

## Background sync

Adapters run on an interval (`SYNC_INTERVAL_MINUTES`, default 60) from inside the
FastAPI lifespan, so CLI commands and tests never trigger network calls. A source
that is not connected is skipped quietly rather than recorded as a failure — an
unconfigured adapter is not an error. `GET /api/sync/status` shows connection
state and the last run per source; `POST /api/sync/all` runs the same work now.

## Charts

The Trends page carries training load (acute vs chronic), the acute:chronic
ratio against its steady-build band, volume by muscle group, and per-exercise
estimated 1RM. Charts are hand-rolled SVG so the mark specs hold exactly: 2px
lines, surface-ringed end markers, hairline grids, bars capped at 24px with
rounded data-ends, crosshair tooltips that list every series at the hovered date,
and a table view so no value is reachable only by hovering. The two-series
palette is validated for colour-vision deficiency against the app's own dark
surface. One filter row scopes every chart below it.

## Backups

Your whole training history is one SQLite file, on a device that can be lost,
wiped or replaced. **Settings → Backups** downloads that file; the same page
restores one.

```bash
curl -OJ http://127.0.0.1:8000/api/backup                     # download
curl -F file=@aura-backup-2026-09-21-1349.db \
     http://127.0.0.1:8000/api/backup/inspect                 # look inside first
```

The format is the database itself, so anything that speaks SQLite can open it —
including the Android app, which is built from the same schema. A backup is how
history moves between the two.

Restoring is deliberately two steps: the file is opened and described before
anything is replaced, so you see what is in it first. A file that is not a
readable Aura database is refused with the reason, and the database a restore
replaces is moved aside rather than deleted, so restoring the wrong file is
recoverable. On PostgreSQL this refuses and points at `pg_dump`, which does the
job properly.

## Running it entirely on a phone

This is the setup the app suits best. Gadgetbridge and FitNotes already run on
your phone, so if the server runs there too, the data never moves between devices
at all — no Syncthing, no cable, no network, nothing to expose.

FastAPI serves the built frontend, so it is one process on one port and needs no
Node at runtime. The browser is on the same device, so loopback is enough and the
absence of authentication stops mattering.

Install [Termux from F-Droid][termux] — not the Play Store build, which is
abandoned — then:

```bash
pkg install git
git clone <this repo> && cd fitness-ai-coach
./scripts/setup.sh
./scripts/start.sh
```

`setup.sh` installs Python and Node, takes a wake lock, creates the SQLite
database, runs the migrations, seeds the catalogue and builds the frontend. There
is no database server on a phone: `data/aura.db` is a file, so nothing else has
to survive Android's process killing.

Then open `http://127.0.0.1:8000` in Chrome and choose **Install app** (or Add to
home screen). It is a progressive web app, so it gets its own icon and opens
without browser chrome. The service worker caches only the shell and never the
API: a dashboard showing yesterday's load as though it were today's is a worse
failure than a blank screen.

This is the route that works today, and the only one where import runs by
itself. The native app under `android/` is a separate thing — see below.

Termux is sandboxed and cannot see shared storage until you grant it — the script
asks, and Android shows a permission dialog. After that `~/storage/shared`
is the usual `/storage/emulated/0`, and either path works in the watch list.

Then point the backups at the app once, in **Settings → Automatic import**:

- **Gadgetbridge** → Settings → Auto export → enabled. Add its folder to the
  watch list. The export is a bare file named `Gadgetbridge` with no extension;
  files are identified by content, so that is fine.
- **FitNotes** → Settings → Backup → automatic backup. Add that folder too.

Set both export locations to an ordinary folder such as `Documents` or
`Download`. On Android 11 and later, apps' own `Android/data/…` directories are
off limits to other apps, Termux included, so a backup written there cannot be
read no matter what you put in the watch list.

After this nothing needs touching again: both apps back themselves up, and the
scheduler imports whatever is new every two minutes.

The real friction is Android, not the install. Background processes get killed,
so `termux-wake-lock` (taken by the scripts) and the battery-optimisation
exemption are what keep the server alive when you switch apps. If the app stops
responding after a while, that is what to check first.

[termux]: https://f-droid.org/packages/com.termux/

## The native app, without a computer

The Android app cannot be built on the phone — Android Studio is desktop-only —
but it does not have to be built by you at all. `.github/workflows/android.yml`
compiles it on every push and attaches the APK to the run, so:

1. Open the repository's **Actions** tab on your phone.
2. Pick the most recent **Android** run.
3. Download the **aura-debug-apk** artifact and open the `.apk` inside it.
4. Android will ask permission to install from your browser. Allow it once.

It is a debug build signed with the throwaway debug key, which is fine for a
personal app but means it will not update over a Play Store install, and the
first launch will warn you about an unknown developer.

That workflow is also the only place `:app` is compiled, so its log is the real
answer to whether the Compose code builds. Until it has run green once, treat
the native app as unproven.

What the native app does **not** do yet: import from the watch folders on a
schedule, or back itself up. Both need Android plumbing rather than more logic —
a foreground service and the storage permission. Until then the Termux app above
is the one that keeps itself fed, and the two share a database format, so a
backup taken from one restores into the other.

## Tests

```bash
cd api && uv run pytest
```

79 tests against a real database built by the real migrations — the SQL views are
exercised, not mocked, since that is where every number the coach quotes comes
from. Each test runs inside a transaction that is rolled back, so tests never see
each other's rows.

The same suite runs against both supported databases:

```bash
cd api && uv run pytest                        # PostgreSQL, creates aura_test
cd api && TEST_DIALECT=sqlite uv run pytest    # SQLite, a scratch file
```

Both must pass. A dialect difference in a view would be silent otherwise — the
coach would simply quote a different number on a phone than on a desktop.

They cover the guarded e1RM formula, warmup exclusion from volume, muscle
attribution and its category fallback, rest days counting as zero load, ACWR,
multi-device metric precedence, unit conversion on import, import idempotency,
file identification by content, and the HTTP contract the web app is written
against.

Verified by mutation: removing the pounds-to-kilograms conversion, accepting
implausible heart rates, and widening the e1RM rep guard each fail exactly the
test that should catch them.

## Status

Working end to end on both PostgreSQL and SQLite: schema and migrations, metrics
views, exercise catalogue, strength logging, FitNotes import, the agent tool
surface, Strava and Health Connect adapters, scheduled sync, backup and restore,
and the Dashboard / Log / Trends / Coach UI.

Started: the native Android app under `android/`. Its `core` module — the
schema, every metrics query, both importers, backup verification and the
coaching loop — is built and tested (`./gradlew :core:test`, 65 tests). The
schema and the coach's tool surface are generated from this app, and import
behaviour is pinned by shared fixtures, so the two cannot drift apart. The
`app` module now has all five screens in Compose — Dashboard, Log, Trends,
Coach and Settings — but has never been built by Gradle, only type-checked
against stubbed Android APIs; see `android/README.md`.

Unverified: the request path to Gemini needs a live `GEMINI_API_KEY`. Everything
it reads is tested, and the tool-schema conversion, stream-part merging and
history round-trip are covered by `tests/test_agent.py`; the network call is not.

`uv run python -m app.agent.coach` lists the models your key can actually call,
if `GEMINI_MODEL` ever needs updating.

## Legacy

The previous Streamlit version — the flat `*.py` scripts, their
`requirements.txt`, the `.bat`/`.ps1` launchers and the GitHub Actions workflow
that ran `sync_all.py` every two hours — has been removed now that the rebuild
covers everything it did. It is in the history if any of it is ever wanted
again: `git log --diff-filter=D -- sync_all.py` finds the commit that removed
it.
