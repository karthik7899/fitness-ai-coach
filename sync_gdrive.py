import os
import io
import tempfile
import sqlite3
import csv
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import google_auth
import db

def download_latest_fitnotes_file():
    creds = google_auth.get_google_credentials()
    if not creds:
        raise ValueError("Google account not authenticated.")
        
    service = build('drive', 'v3', credentials=creds)
    
    # Search for files with 'fitnotes' in the name (covers .fitnotes, FitNotes_Backup, CSV exports, etc.)
    # Ordered by most recently modified
    results = service.files().list(
        q="name contains 'fitnotes' and trashed = false",
        spaces="drive,appDataFolder",
        orderBy="modifiedTime desc",
        pageSize=5,
        fields="files(id, name, mimeType, modifiedTime)"
    ).execute()
    
    files = results.get('files', [])
    if not files:
        print("No FitNotes backup or export files found on Google Drive.")
        return None, None
        
    # Pick the latest file
    latest_file = files[0]
    file_id = latest_file['id']
    file_name = latest_file['name']
    print(f"Found latest FitNotes file on Drive: '{file_name}' (Last modified: {latest_file['modifiedTime']})")
    
    # Download file content
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        
    fh.seek(0)
    return file_name, fh.read()

def parse_fitnotes_sqlite(file_content):
    # Write to a temporary file since sqlite3 needs a path
    temp_path = os.path.join(tempfile.gettempdir(), f"fitnotes_sync_{os.getpid()}.db")
    try:
        with open(temp_path, 'wb') as temp_file:
            temp_file.write(file_content)
    except Exception as e:
        print(f"Error writing temp file: {e}")
        return []
        
    conn = None
    try:
        conn = sqlite3.connect(temp_path)
        cursor = conn.cursor()
        
        # Verify schema table names (Category has capital C in FitNotes)
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cursor.fetchall()]
        
        if "training_log" not in tables or "exercise" not in tables:
            print("Warning: training_log or exercise tables not found in SQLite file.")
            return []
            
        category_table = "Category" if "Category" in tables else ("category" if "category" in tables else None)
        
        # Check if Category table exists and build query dynamically
        if category_table:
            query = f"""
                SELECT 
                    t.date,
                    e.name AS exercise_name,
                    c.name AS category_name,
                    t.metric_weight AS weight,
                    t.reps,
                    t.distance,
                    t.duration_seconds AS time,
                    t.unit
                FROM training_log t
                JOIN exercise e ON t.exercise_id = e._id
                LEFT JOIN {category_table} c ON e.category_id = c._id
            """
        else:
            query = """
                SELECT 
                    t.date,
                    e.name AS exercise_name,
                    'Uncategorized' AS category_name,
                    t.metric_weight AS weight,
                    t.reps,
                    t.distance,
                    t.duration_seconds AS time,
                    t.unit
                FROM training_log t
                JOIN exercise e ON t.exercise_id = e._id
            """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        workouts = []
        for r in rows:
            weight = r[3]
            reps = r[4]
            distance = r[5]
            time_seconds = r[6]
            unit_code = r[7]
            
            # Format time string if duration_seconds is provided
            time_val = None
            if time_seconds and time_seconds > 0:
                mins, secs = divmod(time_seconds, 60)
                hours, mins = divmod(mins, 60)
                if hours > 0:
                    time_val = f"{hours:02d}:{mins:02d}:{secs:02d}"
                else:
                    time_val = f"{mins:02d}:{secs:02d}"
                    
            weight_unit = 'lbs' if unit_code == 1 else 'kg'
            
            # Determine if it's weight/reps (wr) or distance/time (dt)
            kind = 'wr'
            if reps == 0 and (distance > 0 or time_seconds > 0):
                kind = 'dt'
                
            workouts.append({
                'date': r[0],
                'exercise': r[1],
                'category': r[2] if r[2] else 'Uncategorized',
                'weight': float(weight) if weight else 0.0,
                'weight_unit': weight_unit,
                'reps': int(reps) if reps else 0,
                'distance': float(distance) if distance else 0.0,
                'distance_unit': 'km' if distance and distance > 0 else None,
                'time': time_val,
                'notes': '',
                'kind': kind
            })
            
        return workouts
    except Exception as e:
        print(f"Error parsing FitNotes SQLite: {e}")
        return []
    finally:
        if conn:
            conn.close()
        # Cleanup temp file safely on Windows
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception as e:
                print(f"Warning: Could not remove temporary file {temp_path}: {e}")

def parse_fitnotes_csv(file_content_bytes):
    # Decode CSV content
    content_str = file_content_bytes.decode('utf-8-sig', errors='ignore')
    reader = csv.DictReader(io.StringIO(content_str))
    
    workouts = []
    for row in reader:
        # Date, Exercise, Category, Weight (kg), Weight (lbs), Reps, Distance, Distance Unit, Time, Notes, Kind
        date = row.get('Date')
        exercise = row.get('Exercise')
        category = row.get('Category', 'Uncategorized')
        
        # Weight parsing
        weight = 0.0
        weight_unit = 'kg'
        if 'Weight (kg)' in row and row['Weight (kg)']:
            try:
                weight = float(row['Weight (kg)'])
                weight_unit = 'kg'
            except ValueError:
                pass
        elif 'Weight (lbs)' in row and row['Weight (lbs)']:
            try:
                weight = float(row['Weight (lbs)'])
                weight_unit = 'lbs'
            except ValueError:
                pass
                
        # Reps
        reps = 0
        try:
            reps = int(row.get('Reps', 0)) if row.get('Reps') else 0
        except ValueError:
            pass
            
        # Distance
        distance = 0.0
        try:
            distance = float(row.get('Distance', 0.0)) if row.get('Distance') else 0.0
        except ValueError:
            pass
            
        workouts.append({
            'date': date,
            'exercise': exercise,
            'category': category,
            'weight': weight,
            'weight_unit': weight_unit,
            'reps': reps,
            'distance': distance,
            'distance_unit': row.get('Distance Unit'),
            'time': row.get('Time'),
            'notes': row.get('Notes', ''),
            'kind': row.get('Kind', 'wr')
        })
    return workouts

def sync_fitnotes():
    print("Starting FitNotes sync from Google Drive...")
    file_name, content = download_latest_fitnotes_file()
    
    if not file_name or not content:
        print("Sync cancelled: No file fetched.")
        return 0
        
    workouts = []
    # Determine file type based on extension
    if file_name.endswith('.csv'):
        print("Parsing file as FitNotes CSV Export...")
        workouts = parse_fitnotes_csv(content)
    elif file_name.endswith('.fitnotes') or file_name.endswith('.db') or file_name.endswith('.sqlite'):
        print("Parsing file as FitNotes SQLite Database...")
        workouts = parse_fitnotes_sqlite(content)
    else:
        # Fallback check - try SQLite first, then CSV
        try:
            workouts = parse_fitnotes_sqlite(content)
        except Exception:
            try:
                workouts = parse_fitnotes_csv(content)
            except Exception as e:
                print(f"Failed to parse downloaded file '{file_name}': {e}")
                return 0
                
    if workouts:
        db.save_fitnotes_workouts(workouts)
        print(f"Successfully synced {len(workouts)} workout sets into local database.")
        return len(workouts)
    else:
        print("No workouts extracted from the file.")
        return 0

if __name__ == "__main__":
    try:
        # Direct run testing (requires authorization first)
        sync_fitnotes()
    except Exception as e:
        print("Error running sync:", e)
