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
    # Folders owned by other apps, read in place and never modified.
    # Comma-separated, e.g. the FitNotes and Gadgetbridge auto-backup targets.
    watch_dirs: str = ""

    @property
    def inbox_path(self) -> Path:
        return REPO_ROOT / self.inbox_dir

    @property
    def watch_paths(self) -> list[Path]:
        return [Path(p.strip()).expanduser() for p in self.watch_dirs.split(",") if p.strip()]

    @property
    def google_credentials_path(self) -> Path:
        return REPO_ROOT / self.google_credentials_file


settings = Settings()
