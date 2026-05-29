import os
import sqlite3
import json
import logging

# We import psycopg2 only if we are using PostgreSQL to keep SQLite lightweight and dependency-free if running locally.
IS_POSTGRES = False
DATABASE_URL = os.getenv("DATABASE_URL")

# Check if running in Streamlit Cloud context and read from secrets
if not DATABASE_URL:
    try:
        import streamlit as st
        if "DATABASE_URL" in st.secrets:
            DATABASE_URL = st.secrets["DATABASE_URL"]
    except Exception:
        pass

if DATABASE_URL and DATABASE_URL.strip() != "":
    try:
        import psycopg2
        import psycopg2.extras
        IS_POSTGRES = True
    except ImportError:
        logging.warning("DATABASE_URL is set but psycopg2 is not installed. Falling back to SQLite.")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fitness_history.db")

def get_db_connection():
    if IS_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if IS_POSTGRES:
        # PostgreSQL Schema Definitions
        # Use BIGINT for Strava activity IDs since they can exceed standard 32-bit INT capacity
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tokens (
                service VARCHAR(50) PRIMARY KEY,
                token_data TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS strava_activities (
                id BIGINT PRIMARY KEY,
                name TEXT,
                type VARCHAR(50),
                distance REAL,
                moving_time INTEGER,
                elapsed_time INTEGER,
                start_date VARCHAR(50),
                average_speed REAL,
                max_speed REAL,
                calories REAL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fitnotes_workouts (
                id SERIAL PRIMARY KEY,
                date VARCHAR(50),
                exercise TEXT,
                category VARCHAR(100),
                weight REAL,
                weight_unit VARCHAR(10),
                reps INTEGER,
                distance REAL,
                distance_unit VARCHAR(10),
                time VARCHAR(50),
                notes TEXT,
                kind VARCHAR(10)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS google_fit_daily (
                date VARCHAR(50) PRIMARY KEY,
                steps INTEGER DEFAULT 0,
                sleep_hours REAL DEFAULT 0.0,
                active_minutes REAL DEFAULT 0.0
            )
        """)
    else:
        # SQLite Schema Definitions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tokens (
                service TEXT PRIMARY KEY,
                token_data TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS strava_activities (
                id INTEGER PRIMARY KEY,
                name TEXT,
                type TEXT,
                distance REAL,
                moving_time INTEGER,
                elapsed_time INTEGER,
                start_date TEXT,
                average_speed REAL,
                max_speed REAL,
                calories REAL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fitnotes_workouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                exercise TEXT,
                category TEXT,
                weight REAL,
                weight_unit TEXT,
                reps INTEGER,
                distance REAL,
                distance_unit TEXT,
                time TEXT,
                notes TEXT,
                kind TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS google_fit_daily (
                date TEXT PRIMARY KEY,
                steps INTEGER DEFAULT 0,
                sleep_hours REAL DEFAULT 0.0,
                active_minutes REAL DEFAULT 0.0
            )
        """)
        
    conn.commit()
    conn.close()

# Token Helpers
def save_token(service, token_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    token_str = json.dumps(token_data)
    
    if IS_POSTGRES:
        cursor.execute(
            """
            INSERT INTO tokens (service, token_data) VALUES (%s, %s)
            ON CONFLICT (service) DO UPDATE SET token_data = EXCLUDED.token_data
            """,
            (service, token_str)
        )
    else:
        cursor.execute(
            "INSERT OR REPLACE INTO tokens (service, token_data) VALUES (?, ?)",
            (service, token_str)
        )
    conn.commit()
    conn.close()

def get_token(service):
    conn = get_db_connection()
    token_data = None
    
    try:
        if IS_POSTGRES:
            import psycopg2.extras
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cursor.execute("SELECT token_data FROM tokens WHERE service = %s", (service,))
            row = cursor.fetchone()
            if row:
                token_data = row['token_data']
        else:
            cursor = conn.cursor()
            cursor.execute("SELECT token_data FROM tokens WHERE service = ?", (service,))
            row = cursor.fetchone()
            if row:
                token_data = row['token_data']
    finally:
        conn.close()
        
    if token_data:
        return json.loads(token_data)
    return None

def delete_token(service):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if IS_POSTGRES:
        cursor.execute("DELETE FROM tokens WHERE service = %s", (service,))
    else:
        cursor.execute("DELETE FROM tokens WHERE service = ?", (service,))
        
    conn.commit()
    conn.close()

# Strava Helpers
def save_strava_activities(activities):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    for act in activities:
        if IS_POSTGRES:
            cursor.execute("""
                INSERT INTO strava_activities 
                (id, name, type, distance, moving_time, elapsed_time, start_date, average_speed, max_speed, calories)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    type = EXCLUDED.type,
                    distance = EXCLUDED.distance,
                    moving_time = EXCLUDED.moving_time,
                    elapsed_time = EXCLUDED.elapsed_time,
                    start_date = EXCLUDED.start_date,
                    average_speed = EXCLUDED.average_speed,
                    max_speed = EXCLUDED.max_speed,
                    calories = EXCLUDED.calories
            """, (
                act.get('id'),
                act.get('name'),
                act.get('type'),
                act.get('distance'),
                act.get('moving_time'),
                act.get('elapsed_time'),
                act.get('start_date'),
                act.get('average_speed'),
                act.get('max_speed'),
                act.get('calories')
            ))
        else:
            cursor.execute("""
                INSERT OR REPLACE INTO strava_activities 
                (id, name, type, distance, moving_time, elapsed_time, start_date, average_speed, max_speed, calories)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                act.get('id'),
                act.get('name'),
                act.get('type'),
                act.get('distance'),
                act.get('moving_time'),
                act.get('elapsed_time'),
                act.get('start_date'),
                act.get('average_speed'),
                act.get('max_speed'),
                act.get('calories')
            ))
            
    conn.commit()
    conn.close()

# FitNotes Helpers
def save_fitnotes_workouts(workouts):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM fitnotes_workouts")
    
    for w in workouts:
        if IS_POSTGRES:
            cursor.execute("""
                INSERT INTO fitnotes_workouts 
                (date, exercise, category, weight, weight_unit, reps, distance, distance_unit, time, notes, kind)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                w.get('date'),
                w.get('exercise'),
                w.get('category'),
                w.get('weight'),
                w.get('weight_unit', 'kg'),
                w.get('reps'),
                w.get('distance'),
                w.get('distance_unit'),
                w.get('time'),
                w.get('notes'),
                w.get('kind', 'wr')
            ))
        else:
            cursor.execute("""
                INSERT INTO fitnotes_workouts 
                (date, exercise, category, weight, weight_unit, reps, distance, distance_unit, time, notes, kind)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                w.get('date'),
                w.get('exercise'),
                w.get('category'),
                w.get('weight'),
                w.get('weight_unit', 'kg'),
                w.get('reps'),
                w.get('distance'),
                w.get('distance_unit'),
                w.get('time'),
                w.get('notes'),
                w.get('kind', 'wr')
            ))
            
    conn.commit()
    conn.close()

# Google Fit Helpers
def save_google_fit_daily(daily_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    for date, metrics in daily_data.items():
        steps = metrics.get('steps', 0)
        sleep = metrics.get('sleep_hours', 0.0)
        active = metrics.get('active_minutes', 0.0)
        
        if IS_POSTGRES:
            # Upsert logic in Postgres: update metrics only if new data is > 0 (preserves existing data when parsing specific scopes)
            cursor.execute("""
                INSERT INTO google_fit_daily (date, steps, sleep_hours, active_minutes)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (date) DO UPDATE SET
                    steps = CASE WHEN EXCLUDED.steps > 0 THEN EXCLUDED.steps ELSE google_fit_daily.steps END,
                    sleep_hours = CASE WHEN EXCLUDED.sleep_hours > 0.0 THEN EXCLUDED.sleep_hours ELSE google_fit_daily.sleep_hours END,
                    active_minutes = CASE WHEN EXCLUDED.active_minutes > 0.0 THEN EXCLUDED.active_minutes ELSE google_fit_daily.active_minutes END
            """, (date, steps, sleep, active))
        else:
            # SQLite check and upsert logic
            cursor.execute("SELECT steps, sleep_hours, active_minutes FROM google_fit_daily WHERE date = ?", (date,))
            row = cursor.fetchone()
            if row:
                new_steps = steps if steps > 0 else row['steps']
                new_sleep = sleep if sleep > 0 else row['sleep_hours']
                new_active = active if active > 0 else row['active_minutes']
                
                cursor.execute("""
                    UPDATE google_fit_daily 
                    SET steps = ?, sleep_hours = ?, active_minutes = ?
                    WHERE date = ?
                """, (new_steps, new_sleep, new_active, date))
            else:
                cursor.execute("""
                    INSERT INTO google_fit_daily (date, steps, sleep_hours, active_minutes)
                    VALUES (?, ?, ?, ?)
                """, (date, steps, sleep, active))
                
    conn.commit()
    conn.close()

# Initialization check
if __name__ == "__main__":
    init_db()
    db_type = "PostgreSQL (Supabase)" if IS_POSTGRES else "SQLite (Local File)"
    print(f"Database initialized successfully. Type: {db_type}")
