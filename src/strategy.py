import pandas as pd
import numpy as np
import logging
from typing import Optional, List
from src.models import Candle, Signal

logger = logging.getLogger("HybridStrategy")

class HybridStrategy:
    """
    Stratégie Hybride Professionnelle.
    Combinaison de :
    - Tendance de fond (SMA 200)
    - Momentum (SMA 5/20 Cross)
    - Filtre de Volatilité/Régime (ADX)
    - Gestion dynamique du risque (ATR)
    """

    def __init__(self, lookback_period: int = 300):
        self.lookback_period = lookback_period
        # Stockage des bougies par symbole pour calcul vectorisé
        # { "BTCUSDT": [Candle1, Candle2, ...] }
        self.history: dict[str, List[Candle]] = {}
        
        # Paramètres
        self.sma_fast = 5
        self.sma_slow = 20
        self.sma_trend = 200
        self.adx_period = 14
        self.adx_threshold = 25
        self.atr_period = 14
        self.risk_reward_ratio = 1.5

    def on_candle(self, candle: Candle, is_backtest: bool = False) -> Optional[Signal]:
        """
        Traite une nouvelle bougie et génère potentiellement un signal.
        """
        symbol = candle.symbol
        
        # 1. Gestion de l'historique
        if symbol not in self.history:
            self.history[symbol] = []
        self.history[symbol].append(candle)
        
        # On garde une fenêtre glissante pour optimiser la mémoire
        if len(self.history[symbol]) > self.lookback_period:
            self.history[symbol].pop(0)

        # Besoin d'assez de données pour la SMA 200
        if len(self.history[symbol]) < self.sma_trend + 1:
            if not is_backtest: # On ne log pas pendant le warmup pour éviter le spam
                count = len(self.history[symbol])
                if count <= 5 or count % 20 == 0:
                    logger.info(f"⏳ {symbol}: Initialisation indicateurs... ({count}/{self.sma_trend + 1} bougies)")
            return None

        # 2. Conversion en DataFrame Pandas pour calculs vectorisés
        df = self._to_dataframe(self.history[symbol])

        # 3. Calcul des Indicateurs
        df = self._calculate_indicators(df)
        
        # Récupération de la dernière ligne (bougie actuelle) et avant-dernière (pour les croisements)
        curr = df.iloc[-1]
        prev = df.iloc[-2]

        # 4. Logique de Trading
        
        # A. Filtre de Régime (ADX)
        if curr['ADX'] < self.adx_threshold:
            # logger.debug(f"🛡️ Signal ignoré {symbol}: Marché plat (ADX={curr['ADX']:.1f} < 25)")
            return None

        # B. Détermination de la Tendance de Fond
        is_uptrend = curr['close'] > curr['SMA_200']
        is_downtrend = curr['close'] < curr['SMA_200']

        signal_side = None
        reason = ""

        # C. Trigger Momentum (Golden Cross / Death Cross)
        # Cross UP : SMA_Fast croise au-dessus de SMA_Slow
        if prev['SMA_5'] <= prev['SMA_20'] and curr['SMA_5'] > curr['SMA_20']:
            if is_uptrend:
                signal_side = "BUY"
                reason = f"Trend Following LONG (ADX={curr['ADX']:.1f})"
            else:
                logger.info(f"🛡️ Signal LONG ignoré {symbol}: Contre-tendance (Prix < SMA200)")

        # Cross DOWN : SMA_Fast croise en-dessous de SMA_Slow
        elif prev['SMA_5'] >= prev['SMA_20'] and curr['SMA_5'] < curr['SMA_20']:
            if is_downtrend:
                signal_side = "SELL"
                reason = f"Trend Following SHORT (ADX={curr['ADX']:.1f})"
            else:
                logger.info(f"🛡️ Signal SHORT ignoré {symbol}: Contre-tendance (Prix > SMA200)")

        # 5. Génération du Signal avec SL/TP
        if signal_side:
            atr = curr['ATR']
            price = curr['close']
            
            if signal_side == "BUY":
                sl = price - (2.0 * atr)
                tp = price + (3.0 * atr)
            else:
                sl = price + (2.0 * atr)
                tp = price - (3.0 * atr)

            logger.info(f"✅ Signal Validé {symbol}: {signal_side} @ {price} | SL={sl:.2f} TP={tp:.2f} (ATR={atr:.2f})")
            
            return Signal(
                symbol=symbol,
                side=signal_side,
                price=price,
                timestamp=candle.timestamp,
                reason=reason,
                stop_loss=sl,
                take_profit=tp
            )

        return None

    def _to_dataframe(self, candles: List[Candle]) -> pd.DataFrame:
        data = [{
            'timestamp': c.timestamp,
            'open': c.open,
            'high': c.high,
            'low': c.low,
            'close': c.close,
            'volume': c.volume
        } for c in candles]
        return pd.DataFrame(data)

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        # SMA
        df['SMA_5'] = df['close'].rolling(window=self.sma_fast).mean()
        df['SMA_20'] = df['close'].rolling(window=self.sma_slow).mean()
        df['SMA_200'] = df['close'].rolling(window=self.sma_trend).mean()

        # ATR (Average True Range)
        # TR = max(high-low, abs(high-prev_close), abs(low-prev_close))
        prev_close = df['close'].shift(1)
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - prev_close).abs()
        tr3 = (df['low'] - prev_close).abs()
        df['TR'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['ATR'] = df['TR'].rolling(window=self.atr_period).mean()

        # ADX (Average Directional Index)
        # +DM = high - prev_high (si > prev_low - low et > 0)
        # -DM = prev_low - low (si > high - prev_high et > 0)
        prev_high = df['high'].shift(1)
        prev_low = df['low'].shift(1)
        
        up_move = df['high'] - prev_high
        down_move = prev_low - df['low']
        
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        
        # Lissage Wilder (approximé ici par EMA pour performance/simplicité pandas)
        # Pour être précis comme Wilder : alpha = 1/period
        alpha = 1 / self.adx_period
        
        df['TR_smooth'] = df['TR'].ewm(alpha=alpha, adjust=False).mean()
        df['+DM_smooth'] = pd.Series(plus_dm).ewm(alpha=alpha, adjust=False).mean()
        df['-DM_smooth'] = pd.Series(minus_dm).ewm(alpha=alpha, adjust=False).mean()
        
        # DI
        df['+DI'] = 100 * (df['+DM_smooth'] / df['TR_smooth'])
        df['-DI'] = 100 * (df['-DM_smooth'] / df['TR_smooth'])
        
        # DX
        dx = 100 * abs(df['+DI'] - df['-DI']) / (df['+DI'] + df['-DI'])
        
        # ADX
        df['ADX'] = dx.ewm(alpha=alpha, adjust=False).mean()

        return df
