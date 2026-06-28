"""One-time, run-locally helper to bootstrap serverless credentials.

The cloud components (GitHub Actions cron + Streamlit Community Cloud) cannot
open a browser, so the interactive Google OAuth consent has to happen once on
your own machine. This script performs that consent, stores the resulting
token, and prints the values you paste into your hosting secrets.

Usage:
    1. Put your Google desktop OAuth `credentials.json` in this folder.
    2. (Recommended) Set DATABASE_URL to your Supabase Postgres URL so the
       token is written straight into the shared cloud database:
           export DATABASE_URL="postgresql://...supabase..."
    3. Run:  python authorize.py
    4. Copy the printed GOOGLE_TOKEN_JSON into:
         - GitHub repo -> Settings -> Secrets and variables -> Actions
         - Streamlit Community Cloud -> App -> Settings -> Secrets

Strava does not need a browser here: it is authorized through the dashboard
(or any deployment) and refreshes itself from then on.
"""
import json

import db
import google_auth


def main():
    print("=" * 60)
    print(" Aura serverless credential bootstrap")
    print("=" * 60)

    db.init_db()
    db_type = "PostgreSQL/Supabase (shared cloud DB)" if db.IS_POSTGRES else "SQLite (local file only)"
    print(f"\nDatabase target: {db_type}")
    if not db.IS_POSTGRES:
        print("  NOTE: DATABASE_URL is not set, so the token is saved to a local")
        print("  SQLite file. For serverless use, set DATABASE_URL to Supabase and")
        print("  re-run, or copy the GOOGLE_TOKEN_JSON below into your secrets.")

    print("\nLaunching Google consent screen in your browser...")
    creds = google_auth.get_google_credentials(interactive=True)
    if not creds:
        print("\nAuthorization failed or was cancelled.")
        return

    token_dict = google_auth.credentials_to_dict(creds)
    token_json = json.dumps(token_dict)

    print("\nGoogle authorized successfully and saved to the database.\n")
    print("-" * 60)
    print("Add this secret to GitHub Actions AND Streamlit Cloud as")
    print("GOOGLE_TOKEN_JSON (single line):")
    print("-" * 60)
    print(token_json)
    print("-" * 60)

    strava_token = db.get_token('strava')
    if strava_token:
        print("\nStrava token already present in the database -> serverless sync")
        print("will refresh it automatically. Nothing to copy for Strava.")
    else:
        print("\nStrava not connected yet. Authorize it once from the dashboard")
        print("(Streamlit), and the refresh token will be stored in the same DB.")

    print("\nDone. Your scheduled GitHub Actions sync can now run fully headless.")


if __name__ == "__main__":
    main()
