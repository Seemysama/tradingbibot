import asyncio
import logging
from typing import Dict
from src.models import Candle

logger = logging.getLogger("Aggregator")

class TimeBarAggregator:
    """
    Agrégateur de ticks en bougies temporelles (Time Bars).
    Transforme un flux de ticks haute fréquence en bougies OHLCV de 1 seconde.
    """

    def __init__(self, output_queue: asyncio.Queue, interval_ms: int = 1000):
        self.output_queue = output_queue
        self.interval_ms = interval_ms
        # État par symbole : { "BTCUSDT": { "start": 123, "o": ..., "h": ..., "l": ..., "c": ..., "v": ... } }
        self.active_candles: Dict[str, dict] = {}

    async def process_tick(self, tick: dict):
        """
        Traite un tick brut et met à jour la bougie en cours.
        Si le tick appartient à la seconde suivante, émet la bougie précédente.
        """
        symbol = tick['symbol']
        price = tick['price']
        qty = tick['qty']
        ts = tick['timestamp']

        # Calcul du début de la fenêtre temporelle (arrondi à la seconde inférieure)
        # Ex: 1699999999500 // 1000 * 1000 = 1699999999000
        candle_start = (ts // self.interval_ms) * self.interval_ms

        if symbol not in self.active_candles:
            self._init_candle(symbol, candle_start, price, qty)
            return

        current = self.active_candles[symbol]

        # Vérification : est-ce qu'on a changé de seconde ?
        if candle_start > current['start']:
            # 1. Clôturer et émettre la bougie précédente
            await self._emit_candle(symbol)
            # 2. Démarrer une nouvelle bougie avec le tick actuel
            self._init_candle(symbol, candle_start, price, qty)
        else:
            # Mise à jour de la bougie courante (OHLCV)
            current['h'] = max(current['h'], price)
            current['l'] = min(current['l'], price)
            current['c'] = price
            current['v'] += qty

    def _init_candle(self, symbol: str, start: int, price: float, qty: float):
        """Initialise une nouvelle bougie en mémoire."""
        self.active_candles[symbol] = {
            "start": start,
            "o": price,
            "h": price,
            "l": price,
            "c": price,
            "v": qty,
            "symbol": symbol
        }

    async def _emit_candle(self, symbol: str):
        """Transforme le dict interne en objet Candle et le pousse dans la queue."""
        c = self.active_candles[symbol]
        candle = Candle(
            symbol=c['symbol'],
            timestamp=c['start'],
            open=c['o'],
            high=c['h'],
            low=c['l'],
            close=c['c'],
            volume=c['v']
        )
        # Push non-bloquant (ou await si la queue est pleine, ici await par sécurité)
        await self.output_queue.put(candle)
