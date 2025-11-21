import asyncio
import logging
import orjson
import websockets
from asyncio import Queue
from typing import List, Union
from src.config import Settings

logger = logging.getLogger("Ingestor")

class BinanceIngestor:
    """
    Ingestor WebSocket pour Binance Futures.
    Se connecte au flux 'aggTrade' et pousse les données normalisées dans une Queue.
    """

    def __init__(self, symbols: List[str], output_queue: Queue):
        self.symbols = [s.lower().replace('/', '') for s in symbols] # BTC/USDT -> btcusdt
        self.queue = output_queue
        self.base_url = "wss://fstream.binance.com/stream?streams="
        self.running = False

    def _build_url(self) -> str:
        """Construit l'URL WebSocket pour s'abonner à tous les symboles."""
        # Format: btcusdt@aggTrade/ethusdt@aggTrade
        streams = "/".join([f"{s}@aggTrade" for s in self.symbols])
        return f"{self.base_url}{streams}"

    async def run(self):
        """Boucle principale de connexion et d'écoute."""
        self.running = True
        url = self._build_url()
        logger.info(f"📡 Connexion WebSocket Binance Futures pour {len(self.symbols)} symboles...")
        
        backoff = 1
        
        while self.running:
            try:
                async with websockets.connect(url) as ws:
                    logger.info("✅ WebSocket connecté.")
                    backoff = 1 # Reset backoff on success
                    
                    async for message in ws:
                        if not self.running:
                            break
                        await self._process_message(message)
                        
            except (websockets.ConnectionClosed, asyncio.TimeoutError, OSError) as e:
                logger.warning(f"⚠️ Déconnexion WebSocket ({e}). Reconnexion dans {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30) # Max 30s wait
            except Exception as e:
                logger.error(f"❌ Erreur inattendue dans l'ingestor: {e}")
                await asyncio.sleep(5)

    async def _process_message(self, raw_msg: Union[str, bytes]):
        """
        Parse et normalise le message entrant.
        Utilise orjson pour la performance.
        """
        try:
            # Structure Binance Stream: {"stream": "...", "data": {...}}
            payload = orjson.loads(raw_msg)
            data = payload.get('data')
            
            if not data:
                return

            # Extraction optimisée (Event: aggTrade)
            # e: event type, E: event time, s: symbol, a: aggTradeId, p: price, q: quantity, ...
            # m: isBuyerMaker (True = Sell order filled, False = Buy order filled)
            
            normalized_data = {
                'type': 'trade',
                'symbol': data['s'],
                'price': float(data['p']),
                'qty': float(data['q']),
                'side': 'sell' if data['m'] else 'buy', # Si maker est acheteur, c'est un sell market order qui a tapé
                'timestamp': data['T'] # Milliseconds
            }
            
            # Push non-bloquant dans la queue
            self.queue.put_nowait(normalized_data)
            
        except orjson.JSONDecodeError:
            logger.error("❌ Erreur de parsing JSON")
        except KeyError as e:
            logger.error(f"❌ Champ manquant dans le message WebSocket: {e}")
        except Exception as e:
            logger.error(f"❌ Erreur processing message: {e}")
