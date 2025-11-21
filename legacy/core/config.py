"""Configuration management for the trading system."""

import os
from typing import Optional, List
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


@dataclass
class TradingConfig:
    """Trading configuration from environment variables."""
    
    # Trading Mode
    mode: str = "PAPER"  # PAPER or LIVE
    auto_confirm: bool = False
    
    # API Keys
    binance_api_key: str = ""
    binance_api_secret: str = ""
    coinbase_api_key: str = ""
    coinbase_api_secret: str = ""
    coinbase_passphrase: str = ""
    kraken_api_key: str = ""
    kraken_api_secret: str = ""
    
    # API Configuration
    api_url: str = "http://localhost:8000"
    
    # Risk Management
    risk_per_trade: float = 0.01
    daily_dd_max: float = 0.05
    max_leverage: int = 3
    max_concurrent_pos: int = 2
    default_sl_pct: float = 0.01
    default_tp_pct: float = 0.02
    
    # Trading Parameters
    symbols: List[str] = None
    timeframes: List[str] = None
    
    # System Configuration
    heartbeat_interval: int = 60
    lockout_minutes: int = 15
    
    def __post_init__(self):
        """Initialize lists if None."""
        if self.symbols is None:
            self.symbols = ["BTC/USDT"]
        if self.timeframes is None:
            self.timeframes = ["1h"]


def load_config() -> TradingConfig:
    """Load configuration from environment variables."""
    
    # Helper function to parse boolean
    def parse_bool(value: str) -> bool:
        return value.lower() in ("1", "true", "yes", "on")
    
    # Helper function to parse list
    def parse_list(value: str) -> List[str]:
        if not value:
            return []
        return [item.strip() for item in value.split(",") if item.strip()]
    
    return TradingConfig(
        # Trading Mode
        mode="LIVE" if parse_bool(os.getenv("LIVE", "0")) else os.getenv("MODE", "PAPER"),
        auto_confirm=parse_bool(os.getenv("AUTO_CONFIRM", "0")),
        
        # API Keys
        binance_api_key=os.getenv("BINANCE_API_KEY", "") or os.getenv("API_KEY", ""),
        binance_api_secret=os.getenv("BINANCE_API_SECRET", "") or os.getenv("API_SECRET", ""),
        coinbase_api_key=os.getenv("COINBASE_API_KEY", ""),
        coinbase_api_secret=os.getenv("COINBASE_API_SECRET", ""),
        coinbase_passphrase=os.getenv("COINBASE_PASSPHRASE", ""),
        kraken_api_key=os.getenv("KRAKEN_API_KEY", ""),
        kraken_api_secret=os.getenv("KRAKEN_API_SECRET", ""),
        
        # API Configuration
        api_url=os.getenv("API_URL", "http://localhost:8000"),
        
        # Risk Management
        risk_per_trade=float(os.getenv("RISK_PER_TRADE", "0.01")),
        daily_dd_max=float(os.getenv("DAILY_DD_MAX", "0.05")),
        max_leverage=int(os.getenv("MAX_LEVERAGE", "3")),
        max_concurrent_pos=int(os.getenv("MAX_CONCURRENT_POS", "2")),
        default_sl_pct=float(os.getenv("DEFAULT_SL_PCT", "0.01")),
        default_tp_pct=float(os.getenv("DEFAULT_TP_PCT", "0.02")),
        
        # Trading Parameters
        symbols=parse_list(os.getenv("SYMBOLS", "BTC/USDT")),
        timeframes=parse_list(os.getenv("TIMEFRAMES", "1h")),
        
        # System Configuration
        heartbeat_interval=int(os.getenv("HEARTBEAT_INTERVAL", "60")),
        lockout_minutes=int(os.getenv("LOCKOUT_MINUTES", "15")),
    )


# Global config instance
config = load_config()
