import os
import io
import tempfile
import sqlite3
from googleapiclient.discovery import build
import google_auth

def inspect_fitnotes_schema():
    creds = google_auth.get_google_credentials()
    if not creds:
        print("Google not authenticated.")
        return
        
    service = build('drive', 'v3', credentials=creds)
    results = service.files().list(
        q="name = 'FitNotes_Backup.fitnotes' and trashed = false",
        pageSize=1,
        fields="files(id, name)"
    ).execute()
    
    files = results.get('files', [])
    if not files:
        print("Could not find FitNotes_Backup.fitnotes on Google Drive.")
        return
        
    file_id = files[0]['id']
    
    # Download
    print("Downloading database...")
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    from googleapiclient.http import MediaIoBaseDownload
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
        
    fh.seek(0)
    
    # Save to temp
    temp_path = os.path.join(tempfile.gettempdir(), f"fitnotes_inspect_bkup_{os.getpid()}.db")
    with open(temp_path, 'wb') as f:
        f.write(fh.read())
        
    try:
        conn = sqlite3.connect(temp_path)
        cursor = conn.cursor()
        
        # 1. Print all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cursor.fetchall()]
        print("TABLES FOUND IN DATABASE:", tables)
        
        # 2. Print columns for training_log and exercise
        for table in tables:
            if table in ['training_log', 'exercise', 'category', 'set']:
                cursor.execute(f"PRAGMA table_info({table})")
                cols = cursor.fetchall()
                print(f"\nCOLUMNS FOR TABLE '{table}':")
                for col in cols:
                    print(f"  - {col[1]} ({col[2]})")
                    
        conn.close()
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

if __name__ == "__main__":
    inspect_fitnotes_schema()
