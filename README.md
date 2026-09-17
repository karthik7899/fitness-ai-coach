# Aura

A personal training data warehouse with a coaching agent on top. Single user,
local-first: everything runs on your machine and nothing leaves it except the
calls you make to Strava, Google Drive and the Claude API.

The design principle is that **the database is the product**. Ingestion adapters,
the metrics layer, the web UI and the coach are all clients of one canonical
schema.

## Architecture

```
  Strava ──┐
           ├─► adapters ─► raw_records ─► canonical tables ─► SQL views ─┐
Health ────┘   (fetch,     (append-only)   (SI units)       (e1RM, ACWR, │
Connect        normalise,                                    volume)     │
  export       upsert)                                                   │
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

**4. Coach agent.** Claude with a typed tool surface over those views. The model
never does arithmetic — every figure it quotes comes from a tool call. It can
also write: `log_set` records a set from chat, and `remember` persists durable
facts (injuries, goals, constraints) that load into every later conversation.

## Setup

```bash
docker compose up -d                 # Postgres on 127.0.0.1:5432
cp .env.example .env                 # then fill in ANTHROPIC_API_KEY

cd api
uv sync
uv run alembic upgrade head
uv run python -m app.seed            # ~35 exercises with muscle mappings
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

cd ../web
npm install
npm run dev                          # http://127.0.0.1:5173
```

## Data sources

**Strength** is first-party — you log it in the app, so there is no import step.
To bring existing FitNotes history across, import the backup once:

```bash
uv run python -m app.adapters.fitnotes --inspect ~/Downloads/FitNotes_Backup.fitnotes
uv run python -m app.adapters.fitnotes ~/Downloads/FitNotes_Backup.fitnotes
```

Both the `.fitnotes` SQLite backup and the CSV export work. Imported days land
under `source='fitnotes_import'`, separate from anything logged in the app, and
re-running replaces each imported day rather than duplicating it. Weights are
normalised to kilograms on the way in — `--inspect` prints the backup's actual
columns if you want to check the mapping first.

**Strava** connects at `/api/sync/strava/authorize`, then `POST /api/sync/strava`
pulls activities incrementally from the newest one already stored.

**Watch data (Da Fit and anything else on your phone)** arrives through Health
Connect. Google Fit's REST API is not an option for a new build: developer
signups closed in May 2024 and the APIs shut down at the end of 2026, with
[no replacement for the REST API][fit-faq]. Health Connect is on-device and has
no cloud API either — but it can export on a schedule, which is the way in:

1. On your phone, make sure Da Fit syncs to Health Connect. (It definitely
   supports Google Fit; Health Connect support varies by version. If it does not,
   Health Sync is the usual bridge app.)
2. Android Settings → Health Connect → Backup and restore → schedule an export to
   Google Drive.
3. Put a desktop OAuth client JSON at `credentials.json`, then
   `POST /api/sync/health-connect`. The adapter finds the newest export, skips it
   if the archive is unchanged, and unpacks the SQLite database inside.

The export's internal schema is Health Connect's own and shifts between Android
versions, so extraction is schema-discovering: `app/adapters/health_connect.py`
holds candidate table and column names, and `inspect_export()` reports what a
real export actually contains so the mapping can be checked against it.

[fit-faq]: https://developer.android.com/health-and-fitness/health-connect/migration/fit/faq

## Layout

```
api/
  app/
    models.py          canonical schema
    queries.py         shared SQL row helpers
    scheduler.py       interval sync, started by the app lifespan
    adapters/          strava, health_connect, fitnotes, shared run bookkeeping
    agent/             tool definitions + the coaching loop
    routers/           training, metrics, coach (SSE), sync
  alembic/versions/    0001 tables, 0002 metrics views
web/
  src/charts/          LineChart, BarChart, scales and formatting
  src/pages/           Dashboard, Log, Trends, Coach
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

## Status

Working end to end: schema and migrations, metrics views, exercise catalogue,
strength logging, FitNotes import, the agent tool surface, Strava and Health
Connect adapters, scheduled sync, and the Dashboard / Log / Trends / Coach UI.

Unverified: the agent loop itself needs a live `ANTHROPIC_API_KEY`. Everything it
reads is tested; the request path is not.

## Legacy

The flat `*.py` scripts and `.bat`/`.ps1` files in the repository root are the
previous Streamlit version, kept for reference until the rebuild replaces them.
