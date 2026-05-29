import os
import sys
import logging
from datetime import datetime

# Configure logging to write outputs to a file for background monitoring
log_dir = os.path.dirname(os.path.abspath(__file__))
log_file = os.path.join(log_dir, "sync_history.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)

# Import sync scripts
try:
    import db
    import sync_gdrive
    import sync_googlefit
    import sync_strava
    import publish_gdrive
except ImportError as e:
    logging.error(f"Failed to import modules: {e}")
    sys.exit(1)

def run_automated_sync():
    logging.info("========================================")
    logging.info("AUTOMATED FITNESS SYNC INITIATED")
    logging.info("========================================")
    
    # 1. Initialize DB structure if not present
    db.init_db()
    
    # 2. Sync Google Drive (FitNotes Backups)
    logging.info("Syncing FitNotes backups from Google Drive...")
    try:
        sets_count = sync_gdrive.sync_fitnotes()
        logging.info(f"FitNotes Sync Complete: {sets_count} sets loaded.")
    except Exception as e:
        logging.error(f"FitNotes Sync Failed: {e}")
        
    # 3. Sync Google Fit (Da Fit Steps and Sleep)
    logging.info("Syncing Google Fit telemetry...")
    try:
        fit_ok = sync_googlefit.sync_googlefit()
        if fit_ok:
            logging.info("Google Fit Sync Complete.")
        else:
            logging.info("Google Fit: No new telemetry data retrieved.")
    except Exception as e:
        logging.error(f"Google Fit Sync Failed: {e}")
        
    # 4. Sync Strava Activities (Cardio)
    logging.info("Syncing Strava activities...")
    try:
        activities_count = sync_strava.sync_strava_activities()
        logging.info(f"Strava Sync Complete: {activities_count} activities loaded.")
    except Exception as e:
        logging.error(f"Strava Sync Failed: {e}")
        
    # 5. Publish Telemetry to Google Drive
    logging.info("Publishing fitness telemetry to Google Drive...")
    try:
        import google_auth
        if google_auth.is_google_connected():
            pub_ok = publish_gdrive.publish_report_to_gdrive()
            if pub_ok:
                logging.info("Gemini App telemetry profile successfully updated on Google Drive.")
            else:
                logging.warning("Gemini App telemetry profile update failed.")
        else:
            logging.warning("Google account not connected, skipping report publish.")
    except Exception as e:
        logging.error(f"Google Drive Publishing Failed: {e}")

    logging.info("========================================")
    logging.info("AUTOMATED FITNESS SYNC COMPLETED SUCCESSFULLY")
    logging.info("========================================")

if __name__ == "__main__":
    run_automated_sync()
