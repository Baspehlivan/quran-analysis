from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://quran:quran@localhost:55432/quran_analysis"
    data_dir: Path = Path("data")
    model_config = SettingsConfigDict(env_prefix="QURAN_ANALYSIS_", env_file=".env", extra="ignore")


settings = Settings()
