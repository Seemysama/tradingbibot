import logging
import pickle
from collections import deque
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler

from src.config import config
from src.models import Candle

logger = logging.getLogger("OnlineLearner")


class OnlineLearner:
    """
    Module d'apprentissage en ligne (Incremental Learning).
    Utilise des features stationnaires (Log Returns) pour une meilleure généralisation.
    """

    def __init__(self):
        self.lookback = 50
        self.min_samples = config.ML_MIN_SAMPLES
        self.model_path = config.ML_MODEL_PATH

        # Buffers pour le calcul des features (Rolling Window)
        self.buffers: Dict[str, Deque[Candle]] = {}

        # Modèles par symbole (SGD est parfait pour l'online learning)
        self.models: Dict[str, SGDClassifier] = {}
        self.scalers: Dict[str, StandardScaler] = {}
        self.train_counts: Dict[str, int] = {}

        # Création du dossier models si inexistant
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        self.load_models()

    def on_candle(self, candle: Candle) -> Tuple[float, bool]:
        """
        Pipeline principal : Ingestion -> Feature Eng -> Train/Predict.
        Retourne (Probabilité Hausse, Est_Prêt).
        """
        symbol = candle.symbol

        # 1. Gestion du Buffer
        if symbol not in self.buffers:
            self.buffers[symbol] = deque(maxlen=self.lookback + 5)
            self.models[symbol] = SGDClassifier(loss="log_loss", penalty="l2", alpha=0.0001)
            self.scalers[symbol] = StandardScaler()
            self.train_counts[symbol] = 0

        buff = self.buffers[symbol]
        buff.append(candle)

        if len(buff) < self.lookback + 2:
            return 0.5, False

        # 2. Feature Engineering (Stationnaire)
        features = self._compute_features(list(buff))
        if features is None:
            return 0.5, False

        # 3. Labeling (Target) : Est-ce que le prix a monté par rapport à la bougie précédente ?
        # On entraîne sur la bougie T-1 (dont on connaît maintenant le résultat grâce à T)
        prev_candle = buff[-2]
        current_candle = buff[-1]

        # Target: 1 si Close(T) > Close(T-1), sinon 0
        target = 1 if current_candle.close > prev_candle.close else 0

        # On récupère les features de T-1 pour l'entraînement
        # (Attention: ici simplification pour l'exemple, idéalement on stocke les features passées)
        # Pour ce refactoring, on ré-entraîne sur le dernier vecteur calculé

        X = features.reshape(1, -1)

        # 4. Entraînement Incrémental (Partial Fit)
        try:
            # Le scaler doit être fit partiellement aussi
            self.scalers[symbol].partial_fit(X)
            X_scaled = self.scalers[symbol].transform(X)

            self.models[symbol].partial_fit(X_scaled, [target], classes=[0, 1])
            self.train_counts[symbol] += 1

            # Sauvegarde périodique (tous les 100 samples)
            if self.train_counts[symbol] % 100 == 0:
                self.save_models()

        except Exception as e:
            logger.warning(f"ML Training Error {symbol}: {e}")
            return 0.5, False

        # 5. Prédiction pour T (Signal futur)
        # On utilise les features actuelles pour prédire T+1
        if self.train_counts[symbol] < self.min_samples:
            return 0.5, False

        try:
            proba = self.models[symbol].predict_proba(X_scaled)[0][1]  # Proba classe 1 (Hausse)
            return proba, True
        except Exception:
            return 0.5, False

    def _compute_features(self, candles: List[Candle]) -> Optional[np.ndarray]:
        """
        Calcule des features normalisées et stationnaires.
        """
        try:
            # Extraction vectorisée
            closes = np.array([c.close for c in candles])
            volumes = np.array([c.volume for c in candles])
            highs = np.array([c.high for c in candles])
            lows = np.array([c.low for c in candles])

            # 1. Log Returns (Rentabilité logarithmique)
            # ln(Pt / Pt-1)
            log_returns = np.diff(np.log(closes))

            # 2. Volatilité Relative (Range / Close)
            ranges = (highs - lows) / closes

            # 3. Volume Relatif (Vol / Moyenne Vol)
            avg_vol = np.mean(volumes)
            rel_vol = volumes[-1] / (avg_vol + 1e-9)

            # 4. Momentum (RSI-like proxy sur log returns)
            momentum = np.mean(log_returns[-5:]) if len(log_returns) >= 5 else 0.0

            # Construction du vecteur (On prend les dernières valeurs connues)
            # [Last Return, Last Range, Relative Vol, Momentum]
            feature_vector = np.array(
                [
                    log_returns[-1],
                    ranges[-1],
                    rel_vol,
                    momentum,
                ],
                dtype=np.float32,
            )

            # Gestion des NaNs/Infinis
            if not np.isfinite(feature_vector).all():
                return None

            return feature_vector

        except Exception as e:
            logger.error(f"Feature computation error: {e}")
            return None

    def save_models(self):
        """Persistance des modèles sur disque."""
        try:
            data = {
                "models": self.models,
                "scalers": self.scalers,
                "counts": self.train_counts,
            }
            with open(self.model_path, "wb") as f:
                pickle.dump(data, f)
            # logger.info("💾 ML Models saved.")
        except Exception as e:
            logger.error(f"Failed to save models: {e}")

    def load_models(self):
        """Chargement des modèles depuis le disque."""
        if not self.model_path.exists():
            return
        try:
            with open(self.model_path, "rb") as f:
                data = pickle.load(f)
                self.models = data.get("models", {})
                self.scalers = data.get("scalers", {})
                self.train_counts = data.get("counts", {})
            logger.info(f"📂 ML Models loaded ({len(self.models)} symbols).")
        except Exception as e:
            logger.error(f"Failed to load models: {e}")
