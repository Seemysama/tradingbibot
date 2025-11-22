import asyncio
import logging
import ccxt.async_support as ccxt
from datetime import datetime, timedelta, timezone
from tqdm.asyncio import tqdm
from src.config import load_config
from src.database import QuestDBClient

# Configuration logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("Backfill")

async def download_trades(symbol: str, hours: int = 24):
    """
    Télécharge les Klines (Bougies 1s) depuis Binance et les insère dans QuestDB.
    Optimisé pour la vitesse (OHLCV vs Trades).
    """
    config = load_config()
    
    # Initialisation Exchange
    exchange = ccxt.binance({
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future',
        }
    })
    
    # Initialisation QuestDB
    qdb = QuestDBClient(config.QUESTDB_HOST, config.QUESTDB_PORT)
    
    try:
        await qdb.connect()
        
        # Calcul de la fenêtre de temps
        now = datetime.now(timezone.utc)
        start_time = now - timedelta(hours=hours)
        start_ts = int(start_time.timestamp() * 1000)
        end_ts = int(now.timestamp() * 1000)
        
        # NOTE: Binance Futures ne supporte pas les bougies 1s. On utilise 1m.
        timeframe = '1m'
        timeframe_ms = 60 * 1000
        
        logger.info(f"📥 Démarrage du backfill (Klines {timeframe}) pour {symbol}")
        logger.info(f"🕒 Période : {start_time.isoformat()} -> {now.isoformat()}")
        
        # Barre de progression
        pbar = tqdm(total=end_ts - start_ts, desc="Progression Backfill", unit="ms")
        
        current_ts = start_ts
        total_candles = 0
        
        while current_ts < end_ts:
            # Téléchargement des Klines
            # fetch_ohlcv(symbol, timeframe, since, limit)
            ohlcvs = await exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=current_ts, limit=1000)
            
            if not ohlcvs:
                break
                
            # Insertion dans QuestDB
            for candle in ohlcvs:
                # candle = [timestamp, open, high, low, close, volume]
                ts, o, h, l, c, v = candle
                
                await qdb.send_ohlcv(
                    table='ohlcv',  # Nouvelle table dédiée
                    symbol=symbol.replace('/', ''),
                    open=float(o),
                    high=float(h),
                    low=float(l),
                    close=float(c),
                    volume=float(v),
                    timestamp_ms=int(ts)
                )
            
            count = len(ohlcvs)
            total_candles += count
            
            # Mise à jour du curseur
            last_candle_ts = ohlcvs[-1][0]
            pbar.update(last_candle_ts - current_ts)
            
            # Gestion pagination
            if count < 1000:
                current_ts = last_candle_ts + timeframe_ms
            else:
                current_ts = last_candle_ts + timeframe_ms
                
            if current_ts >= end_ts:
                break
                
        pbar.close()
        logger.info(f"✅ Insertion terminée : {total_candles} bougies ({timeframe}) ajoutées.")
        
    except Exception as e:
        logger.error(f"❌ Erreur critique pendant le backfill : {e}")
        raise
    finally:
        qdb.close()
        await exchange.close()

if __name__ == "__main__":
    # Test rapide si exécuté directement
    try:
        asyncio.run(download_trades("BTC/USDT", hours=1))
    except KeyboardInterrupt:
        pass
