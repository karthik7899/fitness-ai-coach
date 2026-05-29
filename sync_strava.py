import os
import time
import requests
from dotenv import load_dotenv
import db

def get_credentials():
    dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(dotenv_path)

    cid = os.getenv("STRAVA_CLIENT_ID")
    csec = os.getenv("STRAVA_CLIENT_SECRET")

    # Fallback to Streamlit secrets if running inside Streamlit
    if not cid or not csec:
        try:
            import streamlit as st
            if not cid and "STRAVA_CLIENT_ID" in st.secrets:
                cid = st.secrets["STRAVA_CLIENT_ID"]
            if not csec and "STRAVA_CLIENT_SECRET" in st.secrets:
                csec = st.secrets["STRAVA_CLIENT_SECRET"]
        except Exception:
            pass

    # Clean any enclosing quotes from text editing
    if cid:
        cid = str(cid).strip('"').strip("'").strip()
    if csec:
        csec = str(csec).strip('"').strip("'").strip()
        
    return cid, csec

def exchange_code_for_token(code):
    client_id, client_secret = get_credentials()
    if not client_id or not client_secret:
        raise ValueError(f"Strava client ID or secret is missing. ID: {client_id}")
        
    url = "https://www.strava.com/oauth/token"
    payload = {
        'client_id': client_id,
        'client_secret': client_secret,
        'code': code,
        'grant_type': 'authorization_code'
    }
    
    response = requests.post(url, data=payload)
    if response.status_code != 200:
        raise Exception(f"Failed to exchange Strava code: {response.text} (Tried client_id: {client_id})")
        
    token_data = response.json()
    # Save the token
    db.save_token('strava', token_data)
    return token_data

def get_strava_access_token():
    token_data = db.get_token('strava')
    if not token_data:
        return None
        
    # Check expiry
    expires_at = token_data.get('expires_at', 0)
    # If expired or expiring in 5 minutes
    if expires_at - 300 < time.time():
        print("Strava token expired or expiring soon. Refreshing...")
        refresh_token = token_data.get('refresh_token')
        if not refresh_token:
            return None
            
        client_id, client_secret = get_credentials()
        if not client_id or not client_secret:
            return None
            
        url = "https://www.strava.com/oauth/token"
        payload = {
            'client_id': client_id,
            'client_secret': client_secret,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token'
        }
        
        response = requests.post(url, data=payload)
        if response.status_code != 200:
            print(f"Failed to refresh Strava token: {response.text}")
            return None
            
        new_token_data = response.json()
        # Merge old and new token data to preserve athlete data if not returned in refresh
        merged_token = {**token_data, **new_token_data}
        db.save_token('strava', merged_token)
        return merged_token.get('access_token')
        
    return token_data.get('access_token')

def sync_strava_activities():
    access_token = get_strava_access_token()
    if not access_token:
        print("Strava is not authenticated.")
        return 0
        
    print("Fetching activities from Strava API...")
    # Fetch last 30 activities
    url = "https://www.strava.com/api/v3/athlete/activities"
    headers = {'Authorization': f"Bearer {access_token}"}
    params = {'per_page': 30}
    
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        print(f"Failed to fetch Strava activities: {response.text}")
        return 0
        
    activities = response.json()
    if activities:
        db.save_strava_activities(activities)
        print(f"Successfully synced {len(activities)} Strava activities.")
        return len(activities)
        
    print("No activities returned from Strava.")
    return 0

def is_strava_connected():
    return get_strava_access_token() is not None

if __name__ == "__main__":
    # Test connection
    if is_strava_connected():
        print("Strava is CONNECTED!")
        sync_strava_activities()
    else:
        print("Strava is NOT connected. Complete the OAuth consent via the dashboard.")
