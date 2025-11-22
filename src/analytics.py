import pandas as pd
import psycopg2
import numpy as np
import warnings
from typing import Tuple, Dict
from src.config import load_config

# Suppress warnings
warnings.simplefilter(action='ignore', category=FutureWarning)
warnings.simplefilter(action='ignore', category=UserWarning)

class VectorBacktester:
    """
    Moteur de backtest vectorisé haute performance utilisant Pandas.
    """
    def __init__(self, symbol: str = "BTCUSDT"):
        self.config = load_config()
        self.symbol = symbol.replace("/", "")
        self.conn_str = f"host={self.config.QUESTDB_HOST} port=8812 user=admin password=quest dbname=qdb"
        self.df_1m = None

    def load_data(self, hours: int = 24):
        """
        Charge les données brutes (bougies 1m) depuis QuestDB en mémoire.
        """
        query = f"""
        SELECT 
            timestamp,
            first(open) as open,
            max(high) as high,
            min(low) as low,
            last(close) as close,
            sum(volume) as volume
        FROM ohlcv
        WHERE symbol = '{self.symbol}' 
        AND timestamp >= dateadd('h', -{hours}, now())
        SAMPLE BY 1m ALIGN TO CALENDAR
        ORDER BY timestamp ASC;
        """
        
        with psycopg2.connect(self.conn_str) as conn:
            self.df_1m = pd.read_sql(query, conn)
            
        # Conversion timestamp et indexation
        self.df_1m['timestamp'] = pd.to_datetime(self.df_1m['timestamp'])
        self.df_1m.set_index('timestamp', inplace=True)
        
        # Nettoyage basique
        self.df_1m.sort_index(inplace=True)
        self.df_1m.ffill(inplace=True)

    def resample(self, timeframe: str) -> pd.DataFrame:
        """
        Ré-échantillonne les données 1m vers un timeframe supérieur.
        """
        if timeframe == '1m':
            return self.df_1m.copy()
            
        # Mapping des règles de resampling
        rule_map = {
            '5m': '5min',
            '15m': '15min',
            '1h': '1h',
            '4h': '4h'
        }
        
        rule = rule_map.get(timeframe)
        if not rule:
            raise ValueError(f"Timeframe non supporté: {timeframe}")
            
        # Agrégation OHLCV correcte
        agg_dict = {
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }
        
        df_resampled = self.df_1m.resample(rule).agg(agg_dict)
        return df_resampled.dropna()

    def run(self, df: pd.DataFrame, fast_period: int, slow_period: int, fee_pct: float = 0.0004) -> Dict:
        """
        Exécute le backtest vectorisé sur un DataFrame donné.
        """
        # Copie légère pour ne pas modifier l'original
        data = df[['close']].copy()
        
        # Calcul des indicateurs
        data['sma_fast'] = data['close'].rolling(window=fast_period).mean()
        data['sma_slow'] = data['close'].rolling(window=slow_period).mean()
        
        # Génération des signaux (1 = Long, -1 = Short, 0 = Neutre)
        # Condition Long : Fast > Slow
        # Condition Short : Fast < Slow
        data['signal'] = 0
        data.loc[data['sma_fast'] > data['sma_slow'], 'signal'] = 1
        data.loc[data['sma_fast'] < data['sma_slow'], 'signal'] = -1
        
        # Détection des changements de position (Trades)
        # position représente l'état actuel (1 détenu, -1 short, 0 cash)
        # On décale d'une période car on trade à l'ouverture de la bougie suivante sur signal de la précédente
        data['position'] = data['signal'].shift(1)
        
        # Calcul des rendements logarithmiques (plus précis pour le cumul)
        data['log_ret'] = np.log(data['close'] / data['close'].shift(1))
        
        # Rendement de la stratégie = Position * Rendement du marché
        data['strategy_ret'] = data['position'] * data['log_ret']
        
        # Calcul des frais
        # On paie des frais à chaque changement de position
        # diff != 0 signifie qu'on a changé de position (ex: 0 -> 1, 1 -> -1, etc.)
        trades = data['position'].diff().fillna(0).abs()
        # Note: passer de 1 à -1 compte pour 2 unités de changement (vendre 2x), 
        # mais en réalité on ferme une position et on en ouvre une autre.
        # Simplification : on compte chaque transaction.
        # Si position passe de 1 à -1 : on vend (close long) et on vend (open short) -> 2 transactions.
        # Donc trades * fee est correct.
        
        # Frais totaux en pourcentage
        total_fees = trades * fee_pct
        
        # Rendement net
        data['net_ret'] = data['strategy_ret'] - total_fees
        
        # Métriques finales
        # Somme des log returns = log(Return Total)
        total_log_return = data['net_ret'].sum()
        total_return_pct = (np.exp(total_log_return) - 1) * 100
        
        # Nombre de trades (chaque changement de position non nul est un trade ou un ensemble de trades)
        # On divise par 2 si on considère un aller-retour, mais ici on compte les exécutions
        num_trades = trades[trades > 0].count()
        
        # Drawdown
        cumulative_ret = data['net_ret'].cumsum().apply(np.exp)
        running_max = cumulative_ret.cummax()
        drawdown = (cumulative_ret - running_max) / running_max
        max_drawdown_pct = drawdown.min() * 100
        
        return {
            'return_pct': total_return_pct,
            'max_drawdown_pct': max_drawdown_pct,
            'num_trades': int(num_trades)
        }
