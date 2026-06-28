import os
import json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import db

SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/drive.appdata',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/fitness.activity.read',
    'https://www.googleapis.com/auth/fitness.sleep.read'
]

CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")


def credentials_to_dict(credentials):
    return {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }


def _load_token_data():
    """Load the stored Google token from any available source.

    Order of precedence (most-portable first so the same token works in
    GitHub Actions, Streamlit Cloud and locally):
      1. GOOGLE_TOKEN_JSON environment variable (CI / hosted secret).
      2. Streamlit secrets ["GOOGLE_TOKEN_JSON"].
      3. The application database (populated by a one-time local authorize).
    """
    raw = os.getenv("GOOGLE_TOKEN_JSON")

    if not raw:
        try:
            import streamlit as st
            if "GOOGLE_TOKEN_JSON" in st.secrets:
                raw = st.secrets["GOOGLE_TOKEN_JSON"]
        except Exception:
            pass

    if raw:
        try:
            return json.loads(raw) if isinstance(raw, str) else dict(raw)
        except Exception as e:
            print(f"Could not parse GOOGLE_TOKEN_JSON: {e}")

    # Fall back to the database (Supabase/Postgres in the cloud, SQLite locally).
    # Tolerate a not-yet-initialized database so callers like
    # is_google_connected() never crash on first run.
    try:
        return db.get_token('google')
    except Exception:
        return None


def get_credentials_silent():
    """Return valid Google credentials without any interactive browser flow.

    Safe to call from GitHub Actions, Streamlit Cloud, or any headless
    context. Refreshes the access token using the stored refresh token and
    persists the refreshed token back to the database. Returns ``None`` when
    no usable token is available instead of launching a local server.
    """
    token_data = _load_token_data()
    if not token_data:
        return None

    try:
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)
    except Exception as e:
        print(f"Could not build Google credentials from stored token: {e}")
        return None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            db.save_token('google', credentials_to_dict(creds))
            return creds
        except Exception as e:
            print(f"Error refreshing Google tokens: {e}")
            return None

    return None


def get_google_credentials(interactive=False):
    """Return Google credentials.

    By default this is fully headless (silent refresh only) so the sync
    scripts behave identically whether they run locally or serverless. The
    interactive desktop OAuth flow is only attempted when ``interactive=True``
    is explicitly requested (e.g. the local "Connect Google" button), and is
    used to bootstrap the very first token.
    """
    db.init_db()

    creds = get_credentials_silent()
    if creds:
        return creds

    if not interactive:
        # Headless caller (CI / hosted). Do not block on a browser.
        return None

    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(
            f"Required file 'credentials.json' not found in project directory. "
            f"Please follow instructions in README.md to download your desktop OAuth credentials."
        )

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    # Run a local server to capture the authorization code. Streamlit runs on
    # 8501, so we let Google pick a dynamic free port.
    creds = flow.run_local_server(port=0, prompt='consent')
    db.save_token('google', credentials_to_dict(creds))
    return creds


def is_google_connected():
    try:
        return get_credentials_silent() is not None
    except Exception:
        return False


if __name__ == "__main__":
    try:
        print("Checking credentials.json...")
        if not os.path.exists(CREDENTIALS_FILE):
            print("WARNING: credentials.json is missing! Interactive OAuth will fail until it is added.")
        else:
            print("credentials.json found. Ready for OAuth.")

        if is_google_connected():
            print("Google is CONNECTED and tokens are valid (silent refresh OK).")
        else:
            print("Google is NOT connected yet. Run 'python authorize.py' once to mint a token.")
    except Exception as e:
        print("Error during check:", e)
