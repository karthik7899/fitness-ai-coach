from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://aura:aura@127.0.0.1:5432/aura"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"

    strava_client_id: str = ""
    strava_client_secret: str = ""

    google_credentials_file: str = "credentials.json"

    unit_system: str = "metric"
    sync_interval_minutes: int = 60

    # Drop FitNotes backups and Gadgetbridge exports here; the scheduler imports them.
    inbox_dir: str = "data/inbox"

    @property
    def inbox_path(self) -> Path:
        return REPO_ROOT / self.inbox_dir

    @property
    def google_credentials_path(self) -> Path:
        return REPO_ROOT / self.google_credentials_file


settings = Settings()
