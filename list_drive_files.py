import os
from googleapiclient.discovery import build
import google_auth

def list_drive_files():
    creds = google_auth.get_google_credentials()
    if not creds:
        print("Error: Google account is not authenticated. Please run the app and connect Google first.")
        return
        
    service = build('drive', 'v3', credentials=creds)
    
    print("--- Searching Regular Google Drive (Visible) ---")
    try:
        results = service.files().list(
            q="trashed = false",
            spaces="drive",
            pageSize=30,
            fields="files(id, name, mimeType, modifiedTime)"
        ).execute()
        files = results.get('files', [])
        if not files:
            print("No visible files found in your main Google Drive.")
        else:
            for f in files:
                if 'fitnotes' in f['name'].lower() or f['name'].endswith('.fitnotes'):
                    print(f"MATCH: '{f['name']}' (ID: {f['id']}, Modified: {f['modifiedTime']})")
                else:
                    print(f"Other file: '{f['name']}'")
    except Exception as e:
        print(f"Error searching regular drive: {e}")
        
    print("\n--- Searching Hidden App Data Folder (appDataFolder) ---")
    try:
        results = service.files().list(
            q="trashed = false",
            spaces="appDataFolder",
            pageSize=30,
            fields="files(id, name, mimeType, modifiedTime)"
        ).execute()
        files = results.get('files', [])
        if not files:
            print("No hidden files found in the FitNotes App Data folder.")
        else:
            for f in files:
                print(f"Found hidden file: '{f['name']}' (ID: {f['id']}, Modified: {f['modifiedTime']})")
    except Exception as e:
        print(f"Error searching appDataFolder: {e}")

if __name__ == "__main__":
    list_drive_files()
