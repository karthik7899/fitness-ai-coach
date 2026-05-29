import os
import io
import tempfile
import sqlite3
from googleapiclient.discovery import build
import google_auth

def inspect_fitnotes_data():
    creds = google_auth.get_google_credentials()
    if not creds:
        return
        
    service = build('drive', 'v3', credentials=creds)
    results = service.files().list(
        q="name = 'FitNotes_Backup.fitnotes' and trashed = false",
        pageSize=1,
        fields="files(id, name)"
    ).execute()
    
    files = results.get('files', [])
    if not files:
        return
        
    file_id = files[0]['id']
    
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    from googleapiclient.http import MediaIoBaseDownload
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
        
    fh.seek(0)
    
    temp_path = os.path.join(tempfile.gettempdir(), f"fitnotes_inspect_data_{os.getpid()}.db")
    with open(temp_path, 'wb') as f:
        f.write(fh.read())
        
    try:
        conn = sqlite3.connect(temp_path)
        cursor = conn.cursor()
        
        # Select first 10 rows
        print("FIRST 10 ROWS OF 'training_log':")
        cursor.execute("SELECT * FROM training_log LIMIT 10")
        cols = [d[0] for d in cursor.description]
        print(cols)
        rows = cursor.fetchall()
        for r in rows:
            print(r)
            
        print("\nFIRST 10 ROWS OF 'exercise':")
        cursor.execute("SELECT * FROM exercise LIMIT 10")
        cols_ex = [d[0] for d in cursor.description]
        print(cols_ex)
        rows_ex = cursor.fetchall()
        for r in rows_ex:
            print(r)
            
        conn.close()
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

if __name__ == "__main__":
    inspect_fitnotes_data()
