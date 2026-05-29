import os
import io
import logging
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import google_auth
import db
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def compile_markdown_report():
    conn = db.get_db_connection()
    
    # 1. Fetch recent data (last 14 days)
    cutoff_date = (datetime.now() - timedelta(days=14)).strftime('%Y-%m-%d')
    
    df_fitnotes = pd.read_sql_query(
        "SELECT * FROM fitnotes_workouts WHERE date >= %s ORDER BY date DESC" if db.IS_POSTGRES
        else "SELECT * FROM fitnotes_workouts WHERE date >= ? ORDER BY date DESC",
        conn, params=(cutoff_date,)
    )
    
    # Strava uses start_date (ISO timestamp format)
    df_strava = pd.read_sql_query(
        "SELECT * FROM strava_activities WHERE start_date >= %s ORDER BY start_date DESC" if db.IS_POSTGRES
        else "SELECT * FROM strava_activities WHERE start_date >= ? ORDER BY start_date DESC",
        conn, params=(cutoff_date,)
    )
    
    df_daily = pd.read_sql_query(
        "SELECT * FROM google_fit_daily WHERE date >= %s ORDER BY date DESC" if db.IS_POSTGRES
        else "SELECT * FROM google_fit_daily WHERE date >= ? ORDER BY date DESC",
        conn, params=(cutoff_date,)
    )
    
    conn.close()
    
    # 2. Build Markdown text
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    md = f"# Aura Fitness Telemetry Profile\n"
    md += f"Last updated: **{now_str}**\n\n"
    md += "This document holds the athlete's fitness telemetry for analysis. Use this data directly to provide personalized feedback.\n\n"
    md += "---\n\n"
    
    # Section A: Daily wellness tracking
    md += "## ❤️ DAILY WELLNESS LOG (LAST 14 DAYS)\n\n"
    if not df_daily.empty:
        md += "| Date | Step Count | Sleep Duration | Active Minutes |\n"
        md += "| :--- | :--- | :--- | :--- |\n"
        for _, row in df_daily.iterrows():
            steps = f"{row['steps']:,}" if row['steps'] else "0"
            sleep = f"{row['sleep_hours']:.1f} hrs" if row['sleep_hours'] else "0.0 hrs"
            active = f"{row['active_minutes']:.1f} mins" if row['active_minutes'] else "0.0 mins"
            md += f"| {row['date']} | {steps} | {sleep} | {active} |\n"
    else:
        md += "* No steps or sleep records synced.\n"
    md += "\n"
    
    # Section B: Cardio activities
    md += "## 🏃 CARDIO ACTIVITIES (LAST 14 DAYS)\n\n"
    if not df_strava.empty:
        for _, row in df_strava.iterrows():
            dist_km = row['distance'] / 1000.0
            duration_mins = row['moving_time'] / 60.0
            
            # Pace min/km
            pace_str = ""
            if row['type'] == 'Run' and dist_km > 0:
                pace_dec = duration_mins / dist_km
                pace_min = int(pace_dec)
                pace_sec = int((pace_dec - pace_min) * 60)
                pace_str = f" | Pace: {pace_min}:{pace_sec:02d} min/km"
                
            date_only = row['start_date'][:10]
            md += f"- **{date_only}** - **{row['type']}**: *{row['name']}*\n"
            md += f"  * Distance: {dist_km:.2f} km | Duration: {duration_mins:.1f} mins{pace_str}\n"
    else:
        md += "* No cardio logs synced.\n"
    md += "\n"
    
    # Section C: Strength logs
    md += "## 💪 STRENGTH WORKOUT LOGS (LAST 14 DAYS)\n\n"
    if not df_fitnotes.empty:
        # Group by date and exercise
        grouped = df_fitnotes.groupby(['date', 'exercise', 'category'])
        current_date = ""
        for (date, exercise, category), group in grouped:
            if date != current_date:
                md += f"### Workout Date: {date}\n"
                current_date = date
                
            sets_str = []
            for _, row in group.iterrows():
                if row['reps'] > 0:
                    sets_str.append(f"{row['reps']} reps @ {row['weight']} {row['weight_unit']}")
                elif row['distance'] > 0:
                    sets_str.append(f"{row['distance']} {row['distance_unit']} in {row['time']}")
                    
            md += f"- **{exercise}** ({category}):\n"
            for idx, s in enumerate(sets_str, 1):
                md += f"  * Set {idx}: {s}\n"
            md += "\n"
    else:
        md += "* No strength training logs synced.\n"
        
    return md

def publish_report_to_gdrive():
    logging.info("Compiling latest fitness telemetry Markdown report...")
    report_content = compile_markdown_report()
    
    creds = google_auth.get_google_credentials()
    if not creds:
        logging.error("Google authentication failed. Cannot publish report to Drive.")
        return False
        
    service = build('drive', 'v3', credentials=creds)
    
    filename = "Aura_Fitness_Telemetry.md"
    file_id = None
    
    # Search for an existing file with this exact name
    logging.info(f"Searching for existing '{filename}' file on Google Drive...")
    try:
        results = service.files().list(
            q=f"name = '{filename}' and trashed = false",
            spaces="drive",
            pageSize=1,
            fields="files(id, name)"
        ).execute()
        files = results.get('files', [])
        if files:
            file_id = files[0]['id']
            logging.info(f"Found existing file with ID: {file_id}. Overwriting...")
    except Exception as e:
        logging.error(f"Search failed: {e}")
        
    # Convert report to bytes stream for upload
    fh = io.BytesIO(report_content.encode('utf-8'))
    media = MediaIoBaseUpload(fh, mimetype='text/markdown', resumable=True)
    
    try:
        if file_id:
            # Overwrite/Update existing file
            service.files().update(
                fileId=file_id,
                media_body=media
            ).execute()
            logging.info("Aura_Fitness_Telemetry.md successfully updated on Google Drive!")
        else:
            # Create a new file
            file_metadata = {
                'name': filename,
                'mimeType': 'text/markdown'
            }
            new_file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            file_id = new_file.get('id')
            logging.info(f"Created new file Aura_Fitness_Telemetry.md on Google Drive (ID: {file_id})")
        return True
    except Exception as e:
        logging.error(f"Failed to publish file to Google Drive: {e}")
        return False

if __name__ == "__main__":
    publish_report_to_gdrive()
