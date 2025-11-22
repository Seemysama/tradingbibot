import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from src.models import Candle, Signal

logger = logging.getLogger("HybridStrategy")


@dataclass
class IndicatorState:
    candles: List[Candle] = field(default_factory=list)


class HybridStrategy:
    """
    Stratégie Hybride SMA/ADX/ATR.
    - Filtre 1 : ADX > 25 (évite les ranges).
    - Filtre 2 : Tendance via SMA200.
    - Déclencheur : Croisement SMA5 / SMA20.
    - Sortie : SL = close -/+ 2*ATR, TP = close +/- 3*ATR.
    """

    def __init__(self, lookback: int = 300):
        self.lookback = lookback
        self.state: Dict[str, IndicatorState] = {}

    def _get_state(self, symbol: str) -> IndicatorState:
        if symbol not in self.state:
            self.state[symbol] = IndicatorState()
        return self.state[symbol]

    def _to_df(self, candles: List[Candle]) -> pd.DataFrame:
        data = [
            {
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ]
        return pd.DataFrame(data)

    def _compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df["SMA5"] = df["close"].rolling(window=5).mean()
        df["SMA20"] = df["close"].rolling(window=20).mean()
        df["SMA200"] = df["close"].rolling(window=200).mean()

        prev_close = df["close"].shift(1)
        tr1 = df["high"] - df["low"]
        tr2 = (df["high"] - prev_close).abs()
        tr3 = (df["low"] - prev_close).abs()
        df["TR"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df["ATR"] = df["TR"].rolling(window=14).mean()

        prev_high = df["high"].shift(1)
        prev_low = df["low"].shift(1)
        up_move = df["high"] - prev_high
        down_move = prev_low - df["low"]
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        alpha = 1 / 14
        df["+DM"] = pd.Series(plus_dm).ewm(alpha=alpha, adjust=False).mean()
        df["-DM"] = pd.Series(minus_dm).ewm(alpha=alpha, adjust=False).mean()
        df["TR_smooth"] = df["TR"].ewm(alpha=alpha, adjust=False).mean()
        df["+DI"] = 100 * (df["+DM"] / df["TR_smooth"])
        df["-DI"] = 100 * (df["-DM"] / df["TR_smooth"])
        dx = 100 * (df["+DI"] - df["-DI"]).abs() / (df["+DI"] + df["-DI"])
        df["ADX"] = dx.ewm(alpha=alpha, adjust=False).mean()

        return df

    def on_candle(self, candle: Candle) -> Optional[Signal]:
        state = self._get_state(candle.symbol)
        state.candles.append(candle)
        if len(state.candles) > self.lookback:
            state.candles.pop(0)

        if len(state.candles) < 201:
            return None

        df = self._to_df(state.candles)
        df = self._compute_indicators(df)
        curr = df.iloc[-1]
        prev = df.iloc[-2]

        # Filtre ADX
        if curr["ADX"] < 25:
            return None

        # Tendance
        is_uptrend = curr["close"] > curr["SMA200"]
        is_downtrend = curr["close"] < curr["SMA200"]

        signal_side: Optional[str] = None
        reason = ""

        # Croisement SMA5 / SMA20
        if prev["SMA5"] <= prev["SMA20"] and curr["SMA5"] > curr["SMA20"] and is_uptrend:
            signal_side = "BUY"
            reason = f"Trend Long ADX={curr['ADX']:.1f}"
        elif prev["SMA5"] >= prev["SMA20"] and curr["SMA5"] < curr["SMA20"] and is_downtrend:
            signal_side = "SELL"
            reason = f"Trend Short ADX={curr['ADX']:.1f}"
        else:
            return None

        atr = curr["ATR"]
        price = curr["close"]
        if signal_side == "BUY":
            sl = price - 2 * atr
            tp = price + 3 * atr
        else:
            sl = price + 2 * atr
            tp = price - 3 * atr

        return Signal(
            symbol=candle.symbol,
            side=signal_side,
            price=price,
            timestamp=candle.timestamp,
            reason=reason,
            stop_loss=sl,
            take_profit=tp,
        )
