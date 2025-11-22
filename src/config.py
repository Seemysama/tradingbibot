import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List
from dotenv import load_dotenv

# Chargement des variables d'environnement
load_dotenv()

@dataclass(frozen=True)
class Settings:
    """
    Configuration centralisée de l'application (Single Source of Truth).
    """
    # --- Exchange ---
    BINANCE_API_KEY: str
    BINANCE_API_SECRET: str
    SYMBOLS: List[str]
    
    # --- Database ---
    QUESTDB_HOST: str
    QUESTDB_PORT: int
    
    # --- Strategy Parameters ---
    STRATEGY_LOOKBACK: int = 300
    SMA_FAST: int = 5
    SMA_SLOW: int = 20
    SMA_TREND: int = 200
    ADX_THRESHOLD: float = 25.0
    ATR_PERIOD: int = 14
    RISK_PER_TRADE: float = 0.01  # 1% du capital
    MAX_POSITION_PCT: float = 0.20 # 20% max par position

    # --- Machine Learning ---
    ML_ENABLED: bool = True
    ML_MIN_CONFIDENCE: float = 0.60
    ML_MIN_SAMPLES: int = 1000
    ML_MODEL_PATH: Path = Path("data/models/learner.pkl")
    
    # --- System / Robustness ---
    WATCHDOG_TIMEOUT: int = 15  # Secondes avant reconnexion WS
    CIRCUIT_BREAKER_DRAWDOWN: float = -0.05  # Arrêt si -5% session PnL

def load_config() -> Settings:
    """Charge et valide la configuration."""
    try:
        return Settings(
            BINANCE_API_KEY=_get_env("BINANCE_API_KEY"),
            BINANCE_API_SECRET=_get_env("BINANCE_API_SECRET"),
            SYMBOLS=[s.strip() for s in _get_env("SYMBOLS").split(',') if s.strip()],
            QUESTDB_HOST=_get_env("QUESTDB_HOST"),
            QUESTDB_PORT=int(_get_env("QUESTDB_PORT")),
            ML_ENABLED=os.getenv("ML_ENABLED", "true").lower() == "true",
            ML_MIN_CONFIDENCE=float(os.getenv("ML_MIN_CONFIDENCE", "0.6")),
            ML_MIN_SAMPLES=int(os.getenv("ML_MIN_SAMPLES", "1000"))
        )
    except Exception as e:
        sys.stderr.write(f"❌ CRITICAL CONFIG ERROR: {e}\n")
        sys.exit(1)

def _get_env(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise ValueError(f"Missing environment variable: {key}")
    return val

# Instance globale
config = load_config()
