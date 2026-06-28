# Running Aura without hosting a server

Aura can run with **no server you manage and no monthly cost**, using three
free, managed pieces:

| Concern            | Serverless choice                          | Cost |
| ------------------ | ------------------------------------------ | ---- |
| Database           | Supabase (managed Postgres)                | Free tier |
| Scheduled sync     | GitHub Actions cron (`.github/workflows`)  | Free for public repos |
| Dashboard (option) | Streamlit Community Cloud                  | Free |
| AI coach (option)  | Official Gemini app + Drive profile        | Free |

The same backbone (Supabase + the cron) powers **both** front-ends, so you can
start with one and add the other later.

```
                       ┌─────────────────────────────┐
   Strava / Google Fit │  GitHub Actions cron        │
   FitNotes (Drive) ──▶│  every 2h: sync_all.py      │──▶ Supabase (Postgres)
                       └─────────────────────────────┘          │
                                                                 ├──▶ Streamlit Cloud dashboard (option A)
                       publish_gdrive ─▶ Drive .md  ─────────────┘
                                                                 └──▶ Official Gemini app (option B)
```

---

## 1. One-time setup (the only manual part)

### a. Create the database (Supabase)
1. Create a free project at <https://supabase.com>.
2. Project Settings → Database → copy the **connection string** (URI). It looks
   like `postgresql://postgres:...@db.<ref>.supabase.co:5432/postgres`.

### b. Mint a Google token locally (once)
The cloud cannot open a browser, so Google's consent screen runs once on your
machine and produces a reusable refresh token.

```bash
pip install -r requirements.txt
export DATABASE_URL="postgresql://...your-supabase-uri..."   # so the token lands in the shared DB
python authorize.py
```

This opens the Google consent screen, saves the token into Supabase, and prints
a single-line `GOOGLE_TOKEN_JSON` value. Keep it for the next step.

### c. Authorize Strava once
Strava is refresh-token based and needs no browser in the cloud. Authorize it
from the dashboard (option A below) or any one run; the refresh token is stored
in the same database and reused automatically.

---

## 2. Turn on the scheduled sync (always needed)

In the GitHub repo: **Settings → Secrets and variables → Actions → New repository
secret**, add:

| Secret               | Value |
| -------------------- | ----- |
| `DATABASE_URL`       | your Supabase connection string |
| `GOOGLE_TOKEN_JSON`  | the value printed by `authorize.py` |
| `STRAVA_CLIENT_ID`   | from <https://www.strava.com/settings/api> |
| `STRAVA_CLIENT_SECRET` | from the same Strava page |

The workflow in `.github/workflows/fitness_sync.yml` runs every 2 hours (and on
demand from the **Actions** tab). It writes all telemetry to Supabase and
publishes `Aura_Fitness_Telemetry.md` to your Google Drive — fully headless.

> `GOOGLE_TOKEN_JSON` is optional if the token is already in Supabase (step 1b
> with `DATABASE_URL` set), but adding it as a secret makes the job
> self-contained.

---

## Option A — Hosted dashboard (Streamlit Community Cloud)

1. Push this repo to GitHub.
2. At <https://share.streamlit.io>, create an app pointing at `app.py`.
3. In the app's **Settings → Secrets**, add (TOML):

   ```toml
   DATABASE_URL = "postgresql://...your-supabase-uri..."
   GEMINI_API_KEY = "your_gemini_key"          # enables the in-app chat
   GOOGLE_TOKEN_JSON = '{"token": "...", ...}'  # the authorize.py value
   STRAVA_CLIENT_ID = "12345"
   STRAVA_CLIENT_SECRET = "..."
   APP_URL = "https://<your-app>.streamlit.app/"
   ```

4. Set the Strava app's **Authorization Callback Domain** to
   `<your-app>.streamlit.app`.

You get the full charts + Gemini chat with no server to run. The **"Connect
Google Account"** button only works locally — when hosted, the
`GOOGLE_TOKEN_JSON` secret provides the connection instead.

---

## Option B — No dashboard at all (official Gemini app)

If you only want to chat about your data, skip Streamlit entirely:

1. Do steps 1 and 2 above.
2. Each sync publishes **`Aura_Fitness_Telemetry.md`** to your Google Drive.
3. In the official **Gemini app**, reference that Drive file (or paste its
   contents) and ask your coaching questions.

Nothing is hosted; GitHub Actions keeps the profile fresh on its own.

---

## How it stays headless

`google_auth.get_google_credentials()` is silent by default — it only refreshes
the stored token and never opens a browser. The interactive consent flow runs
exclusively when explicitly requested (`interactive=True`), which happens only
in the local dashboard button and in `authorize.py`. That is why the same code
runs unchanged locally, in GitHub Actions, and on Streamlit Cloud.
