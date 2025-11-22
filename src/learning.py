import logging
from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler

from src.models import Candle, Signal

logger = logging.getLogger("OnlineLearner")


class OnlineLearner:
    """
    Apprentissage en ligne simple (classification binaire hausse/baisse).
    - Caractéristiques dérivées des dernières bougies (retours, moyennes, volatilité, RSI approximatif).
    - Entraînement incrémental (partial_fit) via SGDClassifier (log loss).
    - Sert de filtre (veto/validation) : on ne renvoie pas un Signal, seulement une proba de hausse.
    """

    def __init__(
        self,
        lookback: int = 50,
        min_train_samples: int = 1000,
        prob_buy: float = 0.60,
        prob_sell: float = 0.40,
    ):
        self.lookback = lookback
        self.min_train_samples = min_train_samples
        self.prob_buy = prob_buy
        self.prob_sell = prob_sell

        # Par symbole
        self.buffers: Dict[str, deque[Candle]] = {}
        self.models: Dict[str, SGDClassifier] = {}
        self.scalers: Dict[str, StandardScaler] = {}
        self.last_features: Dict[str, Tuple[np.ndarray, float]] = {}
        self.train_counts: Dict[str, int] = {}

    def _get_buffer(self, symbol: str) -> deque:
        if symbol not in self.buffers:
            self.buffers[symbol] = deque(maxlen=self.lookback + 2)
        return self.buffers[symbol]

    def _build_features(self, candles: List[Candle]) -> np.ndarray:
        closes = np.array([c.close for c in candles], dtype=np.float64)
        highs = np.array([c.high for c in candles], dtype=np.float64)
        lows = np.array([c.low for c in candles], dtype=np.float64)
        volumes = np.array([c.volume for c in candles], dtype=np.float64)

        ret1 = closes[-1] / closes[-2] - 1.0
        ret5 = closes[-1] / closes[-6] - 1.0 if len(closes) > 6 else ret1
        ret20 = closes[-1] / closes[-21] - 1.0 if len(closes) > 21 else ret5

        sma5 = closes[-5:].mean()
        sma20 = closes[-20:].mean() if len(closes) >= 20 else closes.mean()
        std5 = closes[-5:].std()

        prev_close = np.concatenate([[closes[0]], closes[:-1]])  # décalage vers la droite
        tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev_close), np.abs(lows - prev_close)))
        atr14 = tr[-14:].mean() if len(tr) >= 14 else tr.mean()

        # RSI approx (simple ratio gains/pertes)
        diff = np.diff(closes)
        gains = np.clip(diff, 0, None)
        losses = np.clip(-diff, 0, None)
        avg_gain = gains[-14:].mean() if len(gains) >= 14 else gains.mean() if len(gains) > 0 else 0.0
        avg_loss = losses[-14:].mean() if len(losses) >= 14 else losses.mean() if len(losses) > 0 else 1e-9
        rs = avg_gain / (avg_loss + 1e-9)
        rsi = 100 - (100 / (1 + rs))

        feat = np.array(
            [
                closes[-1],
                ret1,
                ret5,
                ret20,
                sma5,
                sma20,
                std5,
                atr14,
                volumes[-1],
                rsi,
            ],
            dtype=np.float64,
        )
        return feat

    def _get_model(self, symbol: str) -> Tuple[SGDClassifier, StandardScaler]:
        if symbol not in self.models:
            self.models[symbol] = SGDClassifier(loss="log_loss", penalty="l2", max_iter=1, learning_rate="optimal", warm_start=True)
            self.scalers[symbol] = StandardScaler()
            self.train_counts[symbol] = 0
        return self.models[symbol], self.scalers[symbol]

    def on_candle(self, candle: Candle) -> Tuple[Optional[float], bool]:
        buf = self._get_buffer(candle.symbol)
        buf.append(candle)

        if len(buf) < self.lookback + 1:
            return None, False

        feats = self._build_features(list(buf)[-self.lookback - 1 :])  # uses last lookback+1 candles
        model, scaler = self._get_model(candle.symbol)

        # Entraînement: utiliser la cible du point précédent
        if candle.symbol in self.last_features:
            prev_feat, prev_close = self.last_features[candle.symbol]
            target = 1 if candle.close > prev_close else 0

            # Fit scaler + modèle en ligne
            scaler.partial_fit(prev_feat.reshape(1, -1))
            X_train = scaler.transform(prev_feat.reshape(1, -1))
            model.partial_fit(X_train, np.array([target]), classes=np.array([0, 1]))
            self.train_counts[candle.symbol] += 1

        # Mise à jour du cache
        self.last_features[candle.symbol] = (feats, candle.close)

        # Pas de prédiction tant qu'on n'a pas assez appris
        if self.train_counts.get(candle.symbol, 0) < self.min_train_samples:
            if self.train_counts[candle.symbol] in (1, 50, 100, self.min_train_samples):
                logger.info(
                    f"🤖 ML warmup {candle.symbol}: {self.train_counts[candle.symbol]}/{self.min_train_samples}"
                )
            return None, False

        # Prédiction courante
        try:
            X = scaler.transform(feats.reshape(1, -1))
            proba = model.predict_proba(X)[0][1]  # proba de hausse
        except Exception as e:
            logger.warning(f"⚠️ ML prediction error {candle.symbol}: {e}")
            return None, True

        return float(proba), True
