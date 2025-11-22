import logging
import numpy as np
import pandas as pd
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.config import config
from src.models import Candle, Signal
from src.learning import OnlineLearner

logger = logging.getLogger("HybridStrategy")


@dataclass
class StrategyState:
    """État interne de la stratégie pour un symbole."""
    candles: deque = field(default_factory=lambda: deque(maxlen=config.STRATEGY_LOOKBACK))
    

class HybridStrategy:
    """
    Stratégie Optimisée (Incrémentale).
    - Warmup: Vectorisé (Rapide)
    - Live: Rolling Window (Efficace)
    """

    def __init__(self, learner: Optional[OnlineLearner] = None):
        self.learner = learner
        self.states: Dict[str, StrategyState] = {}
        
        # Cache des paramètres pour éviter les lookups répétés
        self.sma_fast = config.SMA_FAST
        self.sma_slow = config.SMA_SLOW
        self.sma_trend = config.SMA_TREND
        self.adx_thresh = config.ADX_THRESHOLD
        self.atr_period = config.ATR_PERIOD

    def _get_state(self, symbol: str) -> StrategyState:
        if symbol not in self.states:
            self.states[symbol] = StrategyState()
        return self.states[symbol]

    def on_candle(self, candle: Candle, is_backtest: bool = False) -> Optional[Signal]:
        """
        Cœur de la stratégie. Appelé à chaque nouvelle bougie.
        """
        # 1. Mise à jour ML (Toujours en premier pour l'apprentissage)
        ml_proba, ml_ready = 0.5, False
        if self.learner:
            ml_proba, ml_ready = self.learner.on_candle(candle)

        # 2. Gestion du State (Rolling Window)
        state = self._get_state(candle.symbol)
        state.candles.append(candle)

        # Pas assez de données ?
        if len(state.candles) < self.sma_trend + 1:
            return None

        # 3. Calcul des Indicateurs
        # Optimisation : On ne convertit en DF que la fenêtre nécessaire (max 300 rows), pas tout l'historique
        # C'est un compromis O(1) mémoire vs O(N_window) CPU, très acceptable.
        df = self._compute_indicators_on_window(list(state.candles))
        
        if df is None or len(df) < 2:
            return None

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        # 4. Logique de Trading (Symbolique)
        signal_side = None
        reason = ""

        # A. Filtre ADX (Régime)
        if curr["ADX"] < self.adx_thresh:
            return None

        # B. Filtre Tendance (SMA 200)
        price = curr["close"]
        is_uptrend = price > curr["SMA200"]
        is_downtrend = price < curr["SMA200"]

        # C. Trigger (Crossover SMA 5/20)
        cross_up = (prev["SMA5"] <= prev["SMA20"]) and (curr["SMA5"] > curr["SMA20"])
        cross_down = (prev["SMA5"] >= prev["SMA20"]) and (curr["SMA5"] < curr["SMA20"])

        if cross_up and is_uptrend:
            signal_side = "BUY"
            reason = f"Trend Follow LONG (ADX={curr['ADX']:.1f})"
        elif cross_down and is_downtrend:
            signal_side = "SELL"
            reason = f"Trend Follow SHORT (ADX={curr['ADX']:.1f})"

        if not signal_side:
            return None

        # 5. Validation ML (Neuro)
        if self.learner and config.ML_ENABLED:
            if ml_ready:
                # Veto Logic
                if signal_side == "BUY" and ml_proba < config.ML_MIN_CONFIDENCE:
                    if not is_backtest:
                        logger.info(f"🛡️ ML VETO {candle.symbol}: BUY bloqué (Proba={ml_proba:.2f})")
                    return None
                
                if signal_side == "SELL" and ml_proba > (1.0 - config.ML_MIN_CONFIDENCE):
                    if not is_backtest:
                        logger.info(f"🛡️ ML VETO {candle.symbol}: SELL bloqué (Proba={ml_proba:.2f})")
                    return None
                
                reason += f" + ML({ml_proba:.2f})"
            else:
                # Fallback si ML pas prêt (Warmup)
                pass

        # 6. Construction du Signal
        atr = curr["ATR"]
        if atr <= 0: 
            return None

        if signal_side == "BUY":
            sl = price - 2.0 * atr
            tp = price + 3.0 * atr
        else:
            sl = price + 2.0 * atr
            tp = price - 3.0 * atr

        return Signal(
            symbol=candle.symbol,
            side=signal_side,
            price=price,
            timestamp=candle.timestamp,
            stop_loss=sl,
            take_profit=tp,
            reason=reason
        )

    def _compute_indicators_on_window(self, candles: List[Candle]) -> Optional[pd.DataFrame]:
        """
        Calcul vectorisé sur une petite fenêtre glissante.
        Beaucoup plus rapide que de recalculer sur 100k bougies.
        """
        try:
            # Conversion rapide (List comprehension est plus rapide que pd.DataFrame.from_records pour les petits objets)
            data = {
                "close": [c.close for c in candles],
                "high": [c.high for c in candles],
                "low": [c.low for c in candles]
            }
            df = pd.DataFrame(data)

            # SMAs
            df["SMA5"] = df["close"].rolling(self.sma_fast).mean()
            df["SMA20"] = df["close"].rolling(self.sma_slow).mean()
            df["SMA200"] = df["close"].rolling(self.sma_trend).mean()

            # ATR (True Range)
            prev_close = df["close"].shift(1)
            tr1 = df["high"] - df["low"]
            tr2 = (df["high"] - prev_close).abs()
            tr3 = (df["low"] - prev_close).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            df["ATR"] = tr.rolling(self.atr_period).mean()

            # ADX (Simplifié pour perf)
            # Note: Pour une précision parfaite, l'ADX nécessite un lissage exponentiel (EWM)
            # qui dépend de l'historique infini. Sur une fenêtre glissante, il y aura une légère déviation
            # au début de la fenêtre, mais négligeable après 300 périodes.
            up = df["high"] - df["high"].shift(1)
            down = df["low"].shift(1) - df["low"]
            
            pos_dm = np.where((up > down) & (up > 0), up, 0.0)
            neg_dm = np.where((down > up) & (down > 0), down, 0.0)
            
            # Utilisation de rolling mean au lieu de EWM pour stabilité sur fenêtre courte
            # ou EWM avec adjust=False si la fenêtre est suffisante
            tr_smooth = tr.rolling(self.atr_period).mean()
            pos_di = 100 * pd.Series(pos_dm).rolling(self.atr_period).mean() / tr_smooth
            neg_di = 100 * pd.Series(neg_dm).rolling(self.atr_period).mean() / tr_smooth
            
            dx = 100 * (pos_di - neg_di).abs() / (pos_di + neg_di)
            df["ADX"] = dx.rolling(self.atr_period).mean()

            return df
        except Exception as e:
            logger.error(f"Indicator Error: {e}")
            return None
