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
docker compose up -d                 # Postgres on 127.0.0.1:5432

cd api
uv sync
uv run alembic upgrade head
uv run python -m app.seed            # ~35 exercises with muscle mappings

cd ../web && npm install && npm run build
cd ../api && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000** — FastAPI serves the built frontend, so that is the
whole app on one port. No `.env` is required: add the API key and the import
folders in the **Settings** tab.

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
    queries.py         shared SQL row helpers
    scheduler.py       interval sync, started by the app lifespan
    settings_store.py  UI settings layered over .env
    adapters/          inbox, fitnotes, gadgetbridge, strava, health_connect
    agent/             tool definitions + the coaching loop
    routers/           training, metrics, coach (SSE), sync, settings
  alembic/versions/    0001 tables, 0002 metrics views, 0003 settings
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

## Running it entirely on a phone

This is the setup the app suits best. Gadgetbridge and FitNotes already run on
your phone, so if the server runs there too, the data never moves between devices
at all — no Syncthing, no cable, no network, nothing to expose.

FastAPI serves the built frontend, so it is one process on one port and needs no
Node at runtime. The browser is on the same device, so loopback is enough and the
absence of authentication stops mattering.

```bash
# Termux, from F-Droid — not the Play Store build
pkg install postgresql python git
termux-wake-lock                     # and allow "stop optimizing battery usage"

initdb $PREFIX/var/lib/postgresql
pg_ctl -D $PREFIX/var/lib/postgresql start
createdb aura

git clone <this repo> && cd aura/api
pip install -e .                     # see the psycopg note below
alembic upgrade head
python -m app.seed
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000` in the phone's browser and add it to the home
screen.

Two wrinkles. **psycopg**: `psycopg[binary]` has no Android wheel, so install
plain `psycopg` — Termux's `postgresql` package provides the libpq it needs.
**The frontend**: `web/dist` has to exist. Either `pkg install nodejs && cd web &&
npm install && npm run build` on the phone, or build it on a computer and copy
the `web/dist` folder across.

Then point the exports at the inbox and nothing needs touching again:

- **Gadgetbridge** → Settings → Auto export → enabled, and set the location to
  `data/inbox/`. The scheduled export is a bare file named `Gadgetbridge` with no
  extension; the inbox identifies files by content, so that is fine.
- **FitNotes** → Settings → Backup → automatic backup, pointed at the same folder.

## Tests

```bash
cd api && uv run pytest
```

58 tests against a real Postgres database built by the real migrations — the SQL
views are exercised, not mocked, since that is where every number the coach
quotes comes from. The suite creates and drops an `aura_test` database, and each
test runs inside a transaction that is rolled back, so tests never see each
other's rows.

They cover the guarded e1RM formula, warmup exclusion from volume, muscle
attribution and its category fallback, rest days counting as zero load, ACWR,
multi-device metric precedence, unit conversion on import, import idempotency,
file identification by content, and the HTTP contract the web app is written
against.

Verified by mutation: removing the pounds-to-kilograms conversion, accepting
implausible heart rates, and widening the e1RM rep guard each fail exactly the
test that should catch them.

## Status

Working end to end: schema and migrations, metrics views, exercise catalogue,
strength logging, FitNotes import, the agent tool surface, Strava and Health
Connect adapters, scheduled sync, and the Dashboard / Log / Trends / Coach UI.

Unverified: the request path to Gemini needs a live `GEMINI_API_KEY`. Everything
it reads is tested, and the tool-schema conversion, stream-part merging and
history round-trip are covered by `tests/test_agent.py`; the network call is not.

`uv run python -m app.agent.coach` lists the models your key can actually call,
if `GEMINI_MODEL` ever needs updating.

## Legacy

The flat `*.py` scripts and `.bat`/`.ps1` files in the repository root are the
previous Streamlit version, kept for reference until the rebuild replaces them.
