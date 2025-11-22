import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import pandas as pd

from src.models import Candle, Signal
from src.learning import OnlineLearner
from src.config import Settings, load_config

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

    def __init__(self, lookback: int = 300, learner: Optional[OnlineLearner] = None, settings: Optional[Settings] = None):
        self.lookback = lookback
        self.state: Dict[str, IndicatorState] = {}
        self.learner = learner
        self.settings = settings or load_config()
        self.ml_enabled = getattr(self.settings, "ML_ENABLED", True)
        self.ml_confidence = getattr(self.settings, "ML_MIN_CONFIDENCE", 0.6)

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
        # ATR sur fenêtre glissante de 14 périodes
        df["ATR"] = df["TR"].rolling(window=14, min_periods=14).mean()

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

    def on_candle(self, candle: Candle, is_backtest: bool = False) -> Optional[Signal]:
        # Étape A (Mise à jour ML)
        ml_proba = 0.5
        ml_ready = False
        if self.learner:
            ml_proba, ml_ready = self.learner.on_candle(candle)

        state = self._get_state(candle.symbol)
        state.candles.append(candle)
        if len(state.candles) > self.lookback:
            state.candles.pop(0)

        if len(state.candles) < 201:
            if not is_backtest:
                count = len(state.candles)
                logger.info(f"⏳ {candle.symbol}: Initialisation indicateurs... ({count}/201 bougies)")
            return None

        df = self._to_df(state.candles)
        df = self._compute_indicators(df)
        curr = df.iloc[-1]
        prev = df.iloc[-2]

        # Filtre ADX
        if curr["ADX"] < 25:
            return None

        price = curr["close"]
        atr_raw = curr["ATR"]
        
        # Étape B (Logique Tech) : Génération du signal technique
        signal = None
        
        # Condition LONG : Cross UP + Tendance Hausse (Prix > SMA200)
        if (prev["SMA5"] <= prev["SMA20"]) and (curr["SMA5"] > curr["SMA20"]):
            if price > curr["SMA200"]:
                sl_dist = 2.0 * atr_raw
                tp_dist = 3.0 * atr_raw
                signal = Signal(
                    symbol=candle.symbol,
                    side="BUY",
                    price=price,
                    timestamp=candle.timestamp,
                    stop_loss=price - sl_dist,
                    take_profit=price + tp_dist,
                    reason=f"Trend Following LONG (ADX={curr['ADX']:.1f})"
                )
            else:
                if not is_backtest:
                    logger.info(f"🛡️ Signal LONG ignoré {candle.symbol}: Contre-tendance (Prix < SMA200)")

        # Condition SHORT : Cross DOWN + Tendance Baisse (Prix < SMA200)
        elif (prev["SMA5"] >= prev["SMA20"]) and (curr["SMA5"] < curr["SMA20"]):
            if price < curr["SMA200"]:
                sl_dist = 2.0 * atr_raw
                tp_dist = 3.0 * atr_raw
                signal = Signal(
                    symbol=candle.symbol,
                    side="SELL",
                    price=price,
                    timestamp=candle.timestamp,
                    stop_loss=price + sl_dist,
                    take_profit=price - tp_dist,
                    reason=f"Trend Following SHORT (ADX={curr['ADX']:.1f})"
                )
            else:
                if not is_backtest:
                    logger.info(f"🛡️ Signal SHORT ignoré {candle.symbol}: Contre-tendance (Prix > SMA200)")

        # Étape C (Filtrage/Fusion) : Validation par le ML
        if signal and self.ml_enabled and self.learner:
            # Si le ML n'est pas prêt, on laisse passer (Fallback classique)
            if not ml_ready:
                if not is_backtest:
                    logger.info(f"⚠️ ML Not Ready ({self.learner.train_counts.get(candle.symbol, 0)} samples) - Signal {signal.side} accepté par défaut.")
                return signal

            min_conf = self.ml_confidence
            is_valid = True
            
            if signal.side == "BUY":
                # On veut une proba de hausse forte
                if ml_proba < min_conf:
                    is_valid = False
            elif signal.side == "SELL":
                # On veut une proba de hausse faible (donc proba baisse forte)
                if ml_proba > (1.0 - min_conf):
                    is_valid = False
            
            if not is_valid:
                if not is_backtest:
                    logger.info(f"🛡️ ML VETO: Signal {signal.side} bloqué sur {signal.symbol} (Proba={ml_proba:.2f})")
                return None
            else:
                if not is_backtest:
                    logger.info(f"✅ ML CONFIRM: Signal {signal.side} validé sur {signal.symbol} (Proba={ml_proba:.2f})")

        return signal
