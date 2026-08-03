"""
Application settings loaded from environment variables.
All overridable via .env or OS environment.
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # DhanHQ credentials
    dhan_access_token: str = ""
    dhan_client_id: str = ""

    # DhanHQ API
    dhan_base_url: str = "https://api.dhan.co/v2"
    dhan_intraday_interval: str = "5"  # 5-minute candles

    # Instrument master
    instrument_master_url: str = (
        "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
    )
    instrument_master_ttl_hours: int = 24

    # Chunking
    chunk_size_days: int = 85
    chunk_overlap_days: int = 1

    # Rate limiting
    rate_limit_rps: float = 8.0
    rate_limit_burst: float = 10.0

    # Retry
    max_retries: int = 5
    retry_min_wait: float = 1.0
    retry_max_wait: float = 60.0

    # Paths
    output_dir: Path = Path("output")
    cache_dir: Path = Path("cache")
    jobs_dir: Path = Path("jobs")

    # Logging
    log_level: str = "INFO"

    # Defaults
    default_exchange_segment: str = "NSE_EQ"
    default_instrument: str = "EQUITY"

    def ensure_dirs(self) -> None:
        """Create required directories if they don't exist."""
        for d in [self.output_dir, self.cache_dir, self.jobs_dir]:
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
