import asyncio
import sys
import uvloop
import logging
import websockets
import httpx
from typing import Optional
from datetime import datetime
from src import config
from src.database import QuestDBClient
from src.ingestion import BinanceIngestor
from src.aggregator import TimeBarAggregator
from src.strategy import HybridStrategy
from src.execution import ExecutionEngine
from src.models import Signal, Candle
from src.learning import OnlineLearner
from src.utils import BroadcastLogHandler

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        BroadcastLogHandler() # Ajout du broadcast vers l'UI
    ]
)
# Réduire le bruit des logs HTTP (PnL Broadcaster)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger("TradingEngine")

# Tailles de queues pour éviter la dérive mémoire tout en conservant un bon débit
TICK_QUEUE_SIZE = 5000
CANDLE_QUEUE_SIZE = 1000
EXECUTION_QUEUE_SIZE = 300
# N ticks boursiers diffusés au front par échantillonnage (fan-out)
TICKER_SAMPLE_RATE = 10

# --- Tâche d'écoute des commandes API (Headless Control) ---
async def api_command_listener(execution_engine: ExecutionEngine, aggregator: TimeBarAggregator):
    """
    Écoute les messages WebSocket du serveur API pour recevoir les ordres manuels.
    """
    uri = "ws://localhost:8000/ws/logs"
    logger.info(f"📡 Connexion au canal de commande API ({uri})...")
    
    while True:
        try:
            async with websockets.connect(uri) as websocket:
                logger.info("✅ Connecté au canal de commande API.")
                while True:
                    message = await websocket.recv()
                    
                    # Détection basique des ordres manuels dans les logs
                    # Format attendu: "⚠️ ORDRE MANUEL REÇU: BUY 0.01 BTCUSDT (LIMIT)"
                    if "ORDRE MANUEL REÇU" in message:
                        try:
                            # Parsing très basique (à améliorer avec un protocole structuré plus tard)
                            parts = message.split(" ")
                            # Ex: ['⚠️', 'ORDRE', 'MANUEL', 'REÇU:', 'BUY', '0.01', 'BTCUSDT', '(LIMIT)']
                            side = parts[4]
                            qty = float(parts[5])
                            symbol = parts[6]
                            
                            # Récupération du prix actuel via l'aggrégateur pour éviter division par zéro
                            current_price = 0.0
                            if symbol in aggregator.active_candles:
                                current_price = aggregator.active_candles[symbol].get('c', 0.0)
                            
                            if current_price == 0.0:
                                logger.warning(f"⚠️ Prix inconnu pour {symbol}, ordre manuel ignoré (risque div/0)")
                                continue

                            logger.info(f"🤖 Traitement Ordre Manuel: {side} {qty} {symbol} @ {current_price}$")
                            
                            # Création d'un Signal
                            signal = Signal(
                                symbol=symbol,
                                side=side,
                                price=current_price,
                                timestamp=int(asyncio.get_event_loop().time() * 1000),
                                reason="MANUAL_UI"
                            )
                            
                            # Injection directe dans le moteur
                            await execution_engine.on_signal(signal)
                            
                        except Exception as e:
                            logger.error(f"❌ Erreur parsing ordre manuel: {e}")

        except asyncio.CancelledError:
            logger.info("🛑 Arrêt du listener API.")
            break
        except Exception as e:
            logger.warning(f"⚠️ Perte connexion API ({e}). Reconnexion dans 5s...")
            await asyncio.sleep(5)

async def pnl_broadcaster(engine: ExecutionEngine, aggregator: TimeBarAggregator):
    """
    Diffuse régulièrement le PnL en se basant sur les derniers marks.
    """
    logger.info("💰 Démarrage du PnL Broadcaster...")
    while True:
        try:
            marks = {sym: c.get("c", c.get("close", 0.0)) for sym, c in aggregator.active_candles.items()}
            for sym, px in marks.items():
                engine.update_mark(sym, px)
            await engine.broadcast_portfolio(price_hint=marks)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❌ Erreur PnL Broadcast: {e}")
        await asyncio.sleep(1)

async def data_writer(queue: asyncio.Queue, db: QuestDBClient):
    """
    Consommateur dédié à l'écriture en base de données.
    Dépile les messages de marché et les envoie à QuestDB via ILP.
    """
    logger.info("💾 Démarrage du Data Writer...")

    backoff = 1
    while True:
        try:
            if db.writer is None or db.writer.is_closing():
                try:
                    await db.connect()
                    backoff = 1
                except Exception as conn_err:
                    logger.warning(f"⚠️ Connexion QuestDB indisponible ({conn_err}). Retry dans {backoff}s.")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    continue

            data = await queue.get()

            try:
                if data.get('type') == 'trade':
                    await db.send(
                        table='trades',
                        symbol=data['symbol'],
                        price=data['price'],
                        qty=data['qty'],
                        side=data['side'],
                        timestamp_ms=data['timestamp']
                    )
            finally:
                queue.task_done()

        except asyncio.CancelledError:
            logger.info("💾 Arrêt du Data Writer...")
            db.close()
            break
        except Exception as e:
            logger.error(f"❌ Erreur Data Writer: {e}")
            backoff = min(backoff * 2, 30)
            await asyncio.sleep(backoff)

async def candle_writer(candle_queue: asyncio.Queue, db: QuestDBClient):
    """
    Persiste les bougies agrégées dans QuestDB (table candles_1s).
    """
    backoff = 1
    while True:
        try:
            if db.writer is None or db.writer.is_closing():
                try:
                    await db.connect()
                    backoff = 1
                except Exception as conn_err:
                    logger.warning(f"⚠️ Connexion QuestDB indisponible (candles) ({conn_err}). Retry dans {backoff}s.")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    continue

            candle = await candle_queue.get()

            try:
                await db.send_ohlcv(
                    table="candles_1s",
                    symbol=candle.symbol,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=candle.volume,
                    timestamp_ms=candle.timestamp
                )
            finally:
                candle_queue.task_done()

        except asyncio.CancelledError:
            logger.info("💾 Arrêt du Candle Writer...")
            db.close()
            break
        except Exception as e:
            logger.error(f"❌ Erreur Candle Writer: {e}")
            backoff = min(backoff * 2, 30)
            await asyncio.sleep(backoff)

async def aggregator_runner(input_queue: asyncio.Queue, aggregator: TimeBarAggregator):
    """
    Consommateur qui alimente l'agrégateur avec des ticks bruts.
    """
    logger.info("⏱️ Démarrage de l'Aggregator Runner...")
    while True:
        try:
            tick = await input_queue.get()
        except asyncio.CancelledError:
            break

        try:
            if tick.get('type') == 'trade':
                await aggregator.process_tick(tick)
        except Exception as e:
            logger.error(f"❌ Erreur Aggregator Runner: {e}")
        finally:
            input_queue.task_done()

    try:
        await aggregator.flush_open_candles()
    except Exception as e:
        logger.error(f"⚠️ Flush aggregator échoué: {e}")

async def strategy_runner(candle_queue: asyncio.Queue, execution_queue: asyncio.Queue, strategy: HybridStrategy):
    """
    Consommateur qui alimente la stratégie avec des bougies.
    """
    logger.info("🧠 Démarrage du Strategy Engine (Candle-based)...")
    while True:
        try:
            candle = await candle_queue.get()
            signal = strategy.on_candle(candle)
            
            if signal:
                # On pousse le signal vers l'exécution au lieu de juste logger
                await execution_queue.put(signal)
                logger.info(f"⚡ SIGNAL {signal.side} @ {signal.price}$ | {signal.symbol} | {signal.reason}")
            
            candle_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❌ Erreur Strategy Runner: {e}")

async def execution_runner(execution_queue: asyncio.Queue, engine: ExecutionEngine):
    """
    Consommateur qui exécute les signaux de trading.
    """
    logger.info("💰 Démarrage de l'Execution Engine...")
    while True:
        try:
            signal = await execution_queue.get()
        except asyncio.CancelledError:
            break

        try:
            await engine.on_signal(signal)
        except Exception as e:
            logger.error(f"❌ Erreur Execution Runner: {e}")
        finally:
            execution_queue.task_done()

async def _broadcast_ticker(client: httpx.AsyncClient, msg: dict):
    """Envoie un ticker échantillonné au frontend (non bloquant grâce au timeout court)."""
    if msg.get("type") != "trade":
        return
    symbol = msg.get("symbol")
    price = msg.get("price")
    if not symbol or price is None:
        return

    payload = {
        "type": "ticker",
        "symbol": symbol,
        "price": price
    }
    try:
        await client.post("http://localhost:8000/internal/broadcast", json=payload, timeout=0.5)
    except Exception:
        # Le broadcast n'est pas critique pour le moteur, on ignore silencieusement
        pass

async def fanout_dispatcher(
    source_queue: asyncio.Queue,
    db_queue: asyncio.Queue,
    agg_queue: asyncio.Queue,
    ticker_sample_rate: int = TICKER_SAMPLE_RATE
):
    """
    Dispatcher qui duplique les ticks vers la DB et l'agrégateur.
    Inclut un broadcast échantillonné pour l'UI sans bloquer le pipeline.
    """
    logger.info("🔀 Démarrage du Dispatcher (fan-out DB/Aggregator)...")
    counter = 0
    async with httpx.AsyncClient(timeout=0.5) as client:
        while True:
            try:
                msg = await source_queue.get()
            except asyncio.CancelledError:
                break

            try:
                if msg.get("type") == "trade":
                    counter += 1
                    if ticker_sample_rate and counter % ticker_sample_rate == 0:
                        await _broadcast_ticker(client, msg)

                await db_queue.put(msg)
                await agg_queue.put(msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Erreur Dispatcher: {e}")
            finally:
                source_queue.task_done()

    logger.info("🔀 Dispatcher arrêté.")

async def candle_dispatcher(
    source_queue: asyncio.Queue,
    strategy_queue: asyncio.Queue,
    persist_queue: asyncio.Queue
):
    """Duplication des bougies: stratégie + persistance."""
    logger.info("🪄 Démarrage du Candle Dispatcher (strategy + store)...")
    while True:
        try:
            candle = await source_queue.get()
        except asyncio.CancelledError:
            break

        try:
            await strategy_queue.put(candle)
            await persist_queue.put(candle)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❌ Erreur Candle Dispatcher: {e}")
        finally:
            source_queue.task_done()

    logger.info("🪄 Candle Dispatcher arrêté.")

async def warmup_strategy(strategy: HybridStrategy, learner: OnlineLearner, db_client: QuestDBClient, symbols: list[str]):
    """
    Préchauffe la Stratégie (SMA) ET le Machine Learning (Learner).
    """
    logger.info("🔥 Démarrage du Warm-up Neuro-Symbolique...")
    total = 0
    for symbol in symbols:
        try:
            # On charge assez d'historique pour que le ML apprenne (ex: 2000 bougies)
            candles_data = await db_client.get_recent_candles(symbol, limit=2000)
            if not candles_data:
                continue
            
            logger.info(f"⏳ Entraînement rapide sur {len(candles_data)} bougies pour {symbol}...")
            
            for c_data in candles_data:
                candle = Candle(
                    symbol=c_data['symbol'],
                    timestamp=c_data['timestamp'],
                    open=c_data['open'], high=c_data['high'], low=c_data['low'], close=c_data['close'], volume=c_data['volume']
                )
                # 1. Entraîner le ML
                learner.on_candle(candle)
                # 2. Initialiser les indicateurs techniques
                strategy.on_candle(candle, is_backtest=True)
            
            total += len(candles_data)
        except Exception as e:
            logger.error(f"❌ Erreur Warmup {symbol}: {e}")
    
    logger.info(f"✅ Warm-up terminé. Cerveau IA entraîné sur {total} points.")

async def main():
    """
    Point d'entrée principal du moteur de trading.
    """
    logger.info("🚀 Démarrage du Trading Engine...")
    
    # 1. Configuration
    settings = config.load_config()
    config.config = settings # Injection de la config globale pour la stratégie
    logger.info(f"✅ Configuration chargée. QuestDB cible: {settings.QUESTDB_HOST}:{settings.QUESTDB_PORT}")

    # 2. Queues (Communication Inter-Processus)
    raw_tick_queue = asyncio.Queue()
    db_queue = asyncio.Queue()
    agg_queue = asyncio.Queue()
    candle_queue = asyncio.Queue()
    strategy_candle_queue = asyncio.Queue()
    candle_store_queue = asyncio.Queue()
    execution_queue = asyncio.Queue()

    # 3. Composants
    db_client = QuestDBClient(host=settings.QUESTDB_HOST, port=settings.QUESTDB_PORT)
    ingestor = BinanceIngestor(symbols=settings.SYMBOLS, output_queue=raw_tick_queue)
    aggregator = TimeBarAggregator(output_queue=candle_queue)
    
    # Module ML (Instancié AVANT la stratégie)
    learner = OnlineLearner(
        lookback=50,
        min_train_samples=settings.ML_MIN_SAMPLES,
        prob_buy=settings.ML_MIN_CONFIDENCE,
        prob_sell=1.0 - settings.ML_MIN_CONFIDENCE
    )
    
    # Stratégie Hybride (SMA + ADX + ATR) + ML
    strategy = HybridStrategy(lookback=300, learner=learner)
    
    # --- WARMUP PHASE ---
    # On préchauffe la stratégie ET le ML avec l'historique
    await warmup_strategy(strategy, learner, db_client, settings.SYMBOLS)
    
    # Execution Engine avec Money Management (Max 20% par trade)
    execution_engine = ExecutionEngine(
        initial_balance=10000.0,
        max_position_pct=0.20,
        cooldown_ms=3000
    )

    logger.info("⚡ Moteur initialisé (Mode: Asynchrone/uvloop)")

    # 4. Lancement des Tâches
    tasks = [
        asyncio.create_task(ingestor.run(), name="ws-ingestor"),
        asyncio.create_task(fanout_dispatcher(raw_tick_queue, db_queue, agg_queue, TICKER_SAMPLE_RATE), name="fanout-dispatcher"),
        asyncio.create_task(data_writer(db_queue, db_client), name="questdb-writer"),
        asyncio.create_task(aggregator_runner(agg_queue, aggregator), name="aggregator-runner"),
        asyncio.create_task(candle_dispatcher(candle_queue, strategy_candle_queue, candle_store_queue), name="candle-dispatcher"),
        asyncio.create_task(candle_writer(candle_store_queue, db_client), name="candle-writer"),
        asyncio.create_task(strategy_runner(strategy_candle_queue, execution_queue, strategy), name="strategy-runner"),
        asyncio.create_task(execution_runner(execution_queue, execution_engine), name="execution-runner"),
        asyncio.create_task(api_command_listener(execution_engine, aggregator), name="api-command-listener"),
        asyncio.create_task(pnl_broadcaster(execution_engine, aggregator), name="pnl-broadcaster")
    ]

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        logger.info("🛑 Arrêt demandé...")
    except Exception:
        logger.exception("❌ Erreur critique, arrêt du moteur...")
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        db_client.close()
        logger.info("👋 Fermeture propre...")

if __name__ == "__main__":
    if sys.platform != "win32":
        uvloop.install()
    asyncio.run(main())
