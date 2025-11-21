import asyncio
import logging
import time
from typing import Optional
from src.config import Settings

logger = logging.getLogger("QuestDB")

class QuestDBClient:
    """
    Client asynchrone optimisé pour QuestDB via le protocole ILP (InfluxDB Line Protocol) sur TCP.
    Gère la connexion brute (Socket) pour éviter l'overhead HTTP.
    """

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self._lock = asyncio.Lock()  # Pour thread-safety asynchrone lors de l'écriture

    async def connect(self):
        """Établit la connexion TCP avec QuestDB."""
        try:
            logger.info(f"🔌 Connexion à QuestDB ({self.host}:{self.port})...")
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            logger.info("✅ Connecté à QuestDB (TCP/ILP).")
        except Exception as e:
            logger.error(f"❌ Échec connexion QuestDB: {e}")
            raise

    async def _ensure_connection(self):
        """Vérifie si la connexion est active, sinon tente de reconnecter."""
        if self.writer is None or self.writer.is_closing():
            logger.warning("⚠️ Connexion QuestDB perdue. Tentative de reconnexion...")
            try:
                await self.connect()
            except Exception:
                # On laisse l'appelant gérer l'échec après une tentative
                pass

    async def send(self, table: str, symbol: str, price: float, qty: float, side: str, timestamp_ms: int):
        """
        Envoie une ligne de données au format ILP.
        Format: table,symbol=BTCUSDT side="buy" price=50000.0,qty=0.1 1699999999999000000\n
        
        Args:
            table: Nom de la table (ex: 'trades')
            symbol: Symbole (ex: 'BTCUSDT')
            price: Prix d'exécution
            qty: Quantité
            side: 'buy' ou 'sell'
            timestamp_ms: Timestamp en millisecondes (sera converti en nanosecondes)
        """
        # Conversion timestamp ms -> ns (QuestDB par défaut)
        timestamp_ns = timestamp_ms * 1_000_000
        
        # Construction de la ligne ILP (f-string est le plus rapide en Python)
        # Attention aux espaces : "table,tags fields timestamp\n"
        # Tags: symbol, side (indexés)
        # Fields: price, qty (non indexés)
        line = f"{table},symbol={symbol},side={side} price={price},qty={qty} {timestamp_ns}\n"
        
        async with self._lock:
            await self._ensure_connection()
            
            if self.writer:
                try:
                    self.writer.write(line.encode('utf-8'))
                    # await self.writer.drain() # Drain peut être coûteux en HFT, on laisse l'OS gérer le buffer TCP
                except Exception as e:
                    logger.error(f"❌ Erreur d'écriture ILP: {e}")
                    # On force la fermeture pour déclencher une reconnexion au prochain appel
                    self.close()

    def close(self):
        """Ferme proprement la connexion."""
        if self.writer:
            try:
                self.writer.close()
            except Exception:
                pass
            self.writer = None
            self.reader = None
