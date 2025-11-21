from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class Candle:
    """Représente une bougie OHLCV agrégée."""
    symbol: str
    timestamp: int  # Début de la bougie en ms
    open: float
    high: float
    low: float
    close: float
    volume: float

@dataclass(frozen=True)
class Signal:
    """Représente un signal de trading généré par la stratégie."""
    symbol: str
    side: Literal["BUY", "SELL"]
    price: float
    timestamp: int
    reason: str
