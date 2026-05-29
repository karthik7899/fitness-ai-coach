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

def get_google_credentials():
    # Make sure database is initialized
    db.init_db()
    
    token_data = db.get_token('google')
    creds = None
    
    if token_data:
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                db.save_token('google', credentials_to_dict(creds))
            except Exception as e:
                print(f"Error refreshing Google tokens: {e}. Re-authenticating...")
                creds = None
        else:
            creds = None
            
        if creds is None:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"Required file 'credentials.json' not found in project directory. "
                    f"Please follow instructions in README.md to download your desktop OAuth credentials."
                )
                
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            # Run local server to capture authorization code. Streamlit runs on 8501, 
            # so we'll let Google pick a dynamic port or standard port.
            creds = flow.run_local_server(port=0, prompt='consent')
            
            db.save_token('google', credentials_to_dict(creds))
            
    return creds

def is_google_connected():
    try:
        token_data = db.get_token('google')
        if not token_data:
            return False
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        if creds.valid:
            return True
        if creds.refresh_token:
            # Try a quick silent refresh
            creds.refresh(Request())
            db.save_token('google', credentials_to_dict(creds))
            return True
        return False
    except Exception:
        return False

if __name__ == "__main__":
    try:
        print("Checking credentials.json...")
        if not os.path.exists(CREDENTIALS_FILE):
            print("WARNING: credentials.json is missing! OAuth will fail until it is added.")
        else:
            print("credentials.json found. Ready for OAuth.")
        
        if is_google_connected():
            print("Google is CONNECTED and tokens are valid!")
        else:
            print("Google is NOT connected yet. Run OAuth via Streamlit dashboard.")
    except Exception as e:
        print("Error during check:", e)
