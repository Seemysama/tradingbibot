import logging
from collections import deque
from typing import Optional, Dict
from src.models import Candle, Signal

logger = logging.getLogger("Strategy")

class MomentumStrategy:
    """
    Stratégie de Momentum basée sur des bougies (Candles).
    Utilise un croisement de moyennes mobiles (SMA) sur des données agrégées.
    """

    def __init__(self, fast_period: int = 5, slow_period: int = 20):
        self.fast_period = fast_period
        self.slow_period = slow_period
        
        # Historique des clôtures : { "BTCUSDT": deque([p1, p2...], maxlen=20) }
        self.history: Dict[str, deque] = {}
        # Somme courante pour optimisation SMA : { "BTCUSDT": float }
        self.sums: Dict[str, float] = {} 
        # État précédent pour détection croisement : { "BTCUSDT": (prev_fast, prev_slow) }
        self.prev_state: Dict[str, tuple] = {}

    def on_candle(self, candle: Candle) -> Optional[Signal]:
        """
        Traite une nouvelle bougie 1s et retourne un Signal si croisement détecté.
        """
        symbol = candle.symbol
        close = candle.close
        
        # Initialisation lazy
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=self.slow_period)
            self.sums[symbol] = 0.0
            self.prev_state[symbol] = (None, None)

        history = self.history[symbol]
        current_sum = self.sums[symbol]

        # Mise à jour incrémentale de la somme (O(1))
        # Si le deque est plein, on retire la valeur qui va sortir de la somme
        if len(history) == self.slow_period:
            current_sum -= history[0]
        
        history.append(close)
        current_sum += close
        self.sums[symbol] = current_sum

        # Pas assez de données pour la SMA lente
        if len(history) < self.slow_period:
            return None

        # Calcul des SMAs
        # SMA Slow : Moyenne sur toute la fenêtre (self.slow_period)
        sma_slow = current_sum / self.slow_period
        
        # SMA Fast : Moyenne sur les N derniers éléments
        # Itération sur 5 éléments est négligeable en coût CPU
        sma_fast = sum(list(history)[-self.fast_period:]) / self.fast_period

        # Logique de croisement
        prev_fast, prev_slow = self.prev_state[symbol]
        signal = None

        if prev_fast is not None and prev_slow is not None:
            # Golden Cross (Fast croise Slow vers le haut) -> BUY
            if prev_fast <= prev_slow and sma_fast > sma_slow:
                signal = Signal(
                    symbol=symbol,
                    side="BUY",
                    price=close,
                    timestamp=candle.timestamp,
                    reason=f"Golden Cross SMA({self.fast_period})={sma_fast:.2f} > SMA({self.slow_period})={sma_slow:.2f}"
                )
            # Death Cross (Fast croise Slow vers le bas) -> SELL
            elif prev_fast >= prev_slow and sma_fast < sma_slow:
                signal = Signal(
                    symbol=symbol,
                    side="SELL",
                    price=close,
                    timestamp=candle.timestamp,
                    reason=f"Death Cross SMA({self.fast_period})={sma_fast:.2f} < SMA({self.slow_period})={sma_slow:.2f}"
                )

        # Sauvegarde de l'état pour le prochain tick
        self.prev_state[symbol] = (sma_fast, sma_slow)
        
        return signal
