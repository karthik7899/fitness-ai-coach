import os
import time
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
import google_auth
import db

def get_time_ranges(days_back=14):
    now = datetime.now(timezone.utc)
    # Start of day x days ago
    start_date = now - timedelta(days=days_back)
    start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Timestamps in ms for aggregate queries
    start_time_ms = int(start_date.timestamp() * 1000)
    end_time_ms = int(now.timestamp() * 1000)
    
    # ISO string format for session list query
    start_time_iso = start_date.isoformat()
    end_time_iso = now.isoformat()
    
    return start_time_ms, end_time_ms, start_time_iso, end_time_iso

def fetch_daily_steps_and_active_minutes(service, start_time_ms, end_time_ms):
    body = {
        "aggregateBy": [
            {
                "dataTypeName": "com.google.step_count.delta",
                "dataSourceId": "derived:com.google.step_count.delta:com.google.android.gms:estimated_steps"
            },
            {
                "dataTypeName": "com.google.active_minutes"
            }
        ],
        "bucketByTime": { "durationMillis": 86400000 }, # 1 day
        "startTimeMillis": start_time_ms,
        "endTimeMillis": end_time_ms
    }
    
    try:
        response = service.users().dataset().aggregate(userId='me', body=body).execute()
        daily_data = {}
        
        for bucket in response.get('bucket', []):
            start_ms = int(bucket['startTimeMillis'])
            # Convert bucket start to local date format
            date_str = datetime.fromtimestamp(start_ms / 1000.0, tz=timezone.utc).strftime('%Y-%m-%d')
            
            steps = 0
            active_mins = 0.0
            
            for dataset in bucket.get('dataset', []):
                for point in dataset.get('point', []):
                    # Check value types
                    for val in point.get('value', []):
                        # We identify data type by looking at source or point schema
                        data_type = point.get('dataTypeName', '')
                        
                        if 'step_count' in data_type or 'steps' in data_type:
                            steps += val.get('intVal', 0)
                        elif 'active_minutes' in data_type:
                            active_mins += val.get('fpVal', 0.0) or val.get('intVal', 0)
                        else:
                            # Fallback check based on value type
                            # If it's an int and we are in the first aggregate index (steps)
                            # Google Fit aggregate list order corresponds to body aggregateBy indices
                            pass
            
            # Since response aggregate order matches body order:
            # index 0: steps, index 1: active minutes
            datasets = bucket.get('dataset', [])
            if len(datasets) >= 2:
                # Steps (index 0)
                for point in datasets[0].get('point', []):
                    for val in point.get('value', []):
                        steps += val.get('intVal', 0)
                # Active Minutes (index 1)
                for point in datasets[1].get('point', []):
                    for val in point.get('value', []):
                        active_mins += val.get('fpVal', 0.0) or val.get('intVal', 0)
            
            daily_data[date_str] = {
                'steps': steps,
                'active_minutes': active_mins,
                'sleep_hours': 0.0
            }
            
        return daily_data
    except Exception as e:
        print(f"Error fetching Google Fit metrics: {e}")
        return {}

def fetch_sleep_sessions(service, start_time_iso, end_time_iso):
    try:
        # activityType=72 is Sleep in Google Fit
        response = service.users().sessions().list(
            userId='me',
            startTime=start_time_iso,
            endTime=end_time_iso,
            activityType=72
        ).execute()
        
        sleep_records = {}
        for session in response.get('session', []):
            start_ms = int(session['startTimeMillis'])
            end_ms = int(session['endTimeMillis'])
            duration_hours = (end_ms - start_ms) / (1000.0 * 60 * 60)
            
            # Storing on the day they woke up (end date of sleep)
            date_str = datetime.fromtimestamp(end_ms / 1000.0, tz=timezone.utc).strftime('%Y-%m-%d')
            
            # In case of multiple sleep segments in one day, sum them
            sleep_records[date_str] = sleep_records.get(date_str, 0.0) + duration_hours
            
        return sleep_records
    except Exception as e:
        print(f"Error fetching sleep sessions: {e}")
        return {}

def sync_googlefit():
    print("Starting Google Fit sync (Da Fit data source)...")
    creds = google_auth.get_google_credentials()
    if not creds:
        print("Sync cancelled: Google account not authenticated.")
        return False
        
    service = build('fitness', 'v1', credentials=creds)
    
    # Get range for last 30 days to populate historical data
    start_time_ms, end_time_ms, start_time_iso, end_time_iso = get_time_ranges(days_back=30)
    
    # Fetch steps and active minutes
    daily_data = fetch_daily_steps_and_active_minutes(service, start_time_ms, end_time_ms)
    
    # Fetch sleep
    sleep_data = fetch_sleep_sessions(service, start_time_iso, end_time_iso)
    
    # Merge sleep into daily data
    for date, sleep_hours in sleep_data.items():
        if date in daily_data:
            daily_data[date]['sleep_hours'] = sleep_hours
        else:
            daily_data[date] = {
                'steps': 0,
                'active_minutes': 0.0,
                'sleep_hours': sleep_hours
            }
            
    if daily_data:
        db.save_google_fit_daily(daily_data)
        print(f"Successfully synced Google Fit data for {len(daily_data)} days.")
        return True
    else:
        print("No daily fitness records fetched.")
        return False

if __name__ == "__main__":
    try:
        sync_googlefit()
    except Exception as e:
        print("Error during direct sync execution:", e)
