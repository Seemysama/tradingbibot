from pydantic_settings import BaseSettings
from typing import List, Optional

class Settings(BaseSettings):
    BINANCE_API_KEY: str = "test_key"
    BINANCE_API_SECRET: str = "test_secret"
    QUESTDB_HOST: str = "localhost"
    QUESTDB_PORT: int = 9000
    SYMBOLS: List[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    
    # Optional settings with defaults
    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "PAPER"

    class Config:
        env_file = ".env"
        extra = "ignore"
