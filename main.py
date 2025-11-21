import asyncio
import sys
import uvloop
import logging
from src import config
from src.database import QuestDBClient
from src.ingestion import BinanceIngestor
from src.aggregator import TimeBarAggregator
from src.strategy import MomentumStrategy
from src.execution import ExecutionEngine

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("TradingEngine")

async def data_writer(queue: asyncio.Queue, db: QuestDBClient):
    """
    Consommateur dédié à l'écriture en base de données.
    Dépile les messages de marché et les envoie à QuestDB via ILP.
    """
    logger.info("💾 Démarrage du Data Writer...")
    
    # Connexion initiale à la DB
    await db.connect()
    
    while True:
        try:
            # Récupération bloquante (await) d'un item dans la queue
            data = await queue.get()
            
            if data['type'] == 'trade':
                await db.send(
                    table='trades',
                    symbol=data['symbol'],
                    price=data['price'],
                    qty=data['qty'],
                    side=data['side'],
                    timestamp_ms=data['timestamp']
                )
            
            # Marquer la tâche comme traitée
            queue.task_done()
            
        except asyncio.CancelledError:
            logger.info("💾 Arrêt du Data Writer...")
            db.close()
            break
        except Exception as e:
            logger.error(f"❌ Erreur Data Writer: {e}")
            # On continue pour ne pas tuer le worker, mais on log l'erreur

async def aggregator_runner(input_queue: asyncio.Queue, aggregator: TimeBarAggregator):
    """
    Consommateur qui alimente l'agrégateur avec des ticks bruts.
    """
    logger.info("⏱️ Démarrage de l'Aggregator Runner...")
    while True:
        try:
            tick = await input_queue.get()
            if tick['type'] == 'trade':
                await aggregator.process_tick(tick)
            input_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❌ Erreur Aggregator Runner: {e}")

async def strategy_runner(candle_queue: asyncio.Queue, execution_queue: asyncio.Queue, strategy: MomentumStrategy):
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
            await engine.execute(signal)
            execution_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❌ Erreur Execution Runner: {e}")

async def dispatcher(input_queue: asyncio.Queue, queues: list[asyncio.Queue]):
    """
    Dispatcher qui duplique les messages entrants vers plusieurs queues de consommation.
    Permet le pattern Fan-out (1 Producteur -> N Consommateurs).
    """
    logger.info("🔀 Démarrage du Dispatcher...")
    while True:
        try:
            data = await input_queue.get()
            for q in queues:
                q.put_nowait(data)
            input_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❌ Erreur Dispatcher: {e}")

async def main():
    """
    Point d'entrée principal du moteur de trading.
    """
    logger.info("🚀 Démarrage du Trading Engine...")
    
    # 1. Chargement de la configuration
    settings = config.load_config()
    logger.info(f"✅ Configuration chargée. QuestDB cible: {settings.QUESTDB_HOST}:{settings.QUESTDB_PORT}")

    # 2. Initialisation des files d'attente
    # Flux Ticks : Ingestor -> Dispatcher
    ingestor_queue = asyncio.Queue()
    
    # Flux Ticks : Dispatcher -> DB & Aggregator
    db_queue = asyncio.Queue()
    aggregator_input_queue = asyncio.Queue()
    
    # Flux Bougies : Aggregator -> Strategy
    candle_queue = asyncio.Queue()
    
    # Flux Signaux : Strategy -> Execution
    execution_queue = asyncio.Queue()

    # 3. Initialisation des composants
    db_client = QuestDBClient(settings.QUESTDB_HOST, settings.QUESTDB_PORT)
    ingestor = BinanceIngestor(settings.SYMBOLS, output_queue=ingestor_queue)
    
    aggregator = TimeBarAggregator(output_queue=candle_queue, interval_ms=1000)
    strategy = MomentumStrategy(fast_period=5, slow_period=20)
    execution = ExecutionEngine(mode="PAPER", initial_balance=10000.0)

    logger.info("⚡ Moteur initialisé (Mode: Asynchrone/uvloop)")
    
    try:
        # 4. Lancement concurrent des tâches
        await asyncio.gather(
            ingestor.run(),
            dispatcher(ingestor_queue, [db_queue, aggregator_input_queue]),
            data_writer(db_queue, db_client),
            aggregator_runner(aggregator_input_queue, aggregator),
            strategy_runner(candle_queue, execution_queue, strategy),
            execution_runner(execution_queue, execution)
        )
        
    except asyncio.CancelledError:
        logger.info("🛑 Arrêt du moteur demandé...")
    except Exception as e:
        logger.error(f"❌ Erreur fatale dans la boucle principale : {e}")
        raise
    finally:
        logger.info("👋 Arrêt propre du système.")

if __name__ == "__main__":
    # Installation de uvloop comme politique par défaut pour asyncio
    # Cela remplace la boucle d'événements standard par une version haute performance
    if sys.version_info >= (3, 11):
        with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
            runner.run(main())
    else:
        uvloop.install()
        asyncio.run(main())
