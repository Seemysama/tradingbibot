import logging
import pandas as pd
import psycopg2
import asyncio
import warnings
from typing import List
from src.config import Settings
from src.models import Candle
from src.strategy import MomentumStrategy
from src.execution import ExecutionEngine

# Suppress pandas/sql warnings
warnings.filterwarnings('ignore')

# Configuration logging spécifique pour le backtest
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("Backtest")

class Backtester:
    """
    Moteur de Backtest qui rejoue l'historique QuestDB.
    """

    def __init__(self, config: Settings):
        self.config = config
        # Connexion SQL à QuestDB (Port PG Wire 8812)
        # Default QuestDB credentials: admin / quest
        self.conn_str = f"host={config.QUESTDB_HOST} port=8812 user=admin password=quest dbname=qdb"
        
    def fetch_data(self, symbol: str, hours: int = 24) -> pd.DataFrame:
        """
        Récupère les données historiques agrégées depuis QuestDB.
        Lit depuis la table 'ohlcv' (données 1s) et agrège en 1m.
        """
        # Normalisation du symbole pour QuestDB (ex: BTC/USDT -> BTCUSDT)
        db_symbol = symbol.replace("/", "")
        logger.info(f"📥 Récupération des données pour {db_symbol} (Original: {symbol}) sur les dernières {hours}h...")
        
        # On récupère tout l'historique disponible pour le symbole
        # SAMPLE BY 1m agrège les bougies 1s en bougies 1m
        query = f"""
        SELECT 
            timestamp,
            first(open) as open,
            max(high) as high,
            min(low) as low,
            last(close) as close,
            sum(volume) as volume
        FROM ohlcv
        WHERE symbol = '{db_symbol}' 
        AND timestamp >= dateadd('h', -{hours}, now())
        SAMPLE BY 1m ALIGN TO CALENDAR
        ORDER BY timestamp ASC;
        """
        
        try:
            with psycopg2.connect(self.conn_str) as conn:
                df = pd.read_sql(query, conn)
                if not df.empty:
                    # Conversion timestamp QuestDB (datetime64[ns]) vers int ms
                    df['timestamp'] = df['timestamp'].astype('int64') // 10**6
                    logger.info(f"✅ {len(df)} bougies récupérées.")
                else:
                    logger.warning("⚠️ Aucune donnée trouvée (DataFrame vide).")
                return df
        except Exception as e:
            logger.error(f"❌ Erreur SQL QuestDB: {e}")
            return pd.DataFrame()

    async def run(self, symbol: str):
        """Exécute le backtest."""
        df = self.fetch_data(symbol)
        if df.empty:
            logger.warning("⚠️ Aucune donnée à tester.")
            return

        # Initialisation des composants
        strategy = MomentumStrategy(fast_period=5, slow_period=20)
        execution = ExecutionEngine(mode="PAPER", initial_balance=10000.0)
        
        logger.info("▶️ Démarrage de la simulation...")
        
        # Boucle de simulation (Replay)
        last_price = 0.0
        for _, row in df.iterrows():
            # Construction de la bougie
            candle = Candle(
                symbol=symbol,
                timestamp=int(row['timestamp']),
                open=row['open'],
                high=row['high'],
                low=row['low'],
                close=row['close'],
                volume=row['volume']
            )
            last_price = row['close']
            
            # Injection dans la stratégie
            signal = strategy.on_candle(candle)
            
            # Exécution si signal
            if signal:
                await execution.on_signal(signal)

        # Rapport final
        self._print_report(execution, last_price)

    def _print_report(self, execution: ExecutionEngine, last_price: float):
        initial = execution.initial_balance
        final_equity = execution.get_equity(last_price)
        total_pnl = final_equity - initial
        total_return_pct = (total_pnl / initial) * 100
        
        print("\n" + "="*40)
        print(f"📊 RAPPORT DE BACKTEST")
        print("="*40)
        print(f"Capital Initial : {initial:.2f} $")
        print(f"Equity Finale   : {final_equity:.2f} $ (Mark-to-Market @ {last_price:.2f}$)")
        print(f"PnL Total       : {total_pnl:+.2f} $")
        print(f"Performance     : {total_return_pct:+.2f} %")
        print(f"Solde Cash      : {execution.portfolio.balance:.2f} $")
        print("="*40 + "\n")
