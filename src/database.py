import asyncio
import logging
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

    async def send_ohlcv(self, table: str, symbol: str, open: float, high: float, low: float, close: float, volume: float, timestamp_ms: int):
        """
        Envoie une bougie (OHLCV) au format ILP.
        """
        timestamp_ns = timestamp_ms * 1_000_000
        # Tags: symbol
        # Fields: open, high, low, close, volume
        line = f"{table},symbol={symbol} open={open},high={high},low={low},close={close},volume={volume} {timestamp_ns}\n"
        
        async with self._lock:
            await self._ensure_connection()
            if self.writer:
                try:
                    self.writer.write(line.encode('utf-8'))
                except Exception as e:
                    logger.error(f"❌ Erreur d'écriture ILP (OHLCV): {e}")
                    self.close()

    def close(self):
        """Ferme proprement la connexion."""
        if self.writer:
            try:
                self.writer.close()
            except Exception:
                pass

    async def get_recent_candles(self, symbol: str, limit: int = 300) -> list[dict]:
        """
        Récupère les dernières bougies via REST.
        Priorité: table de bougies (candles_1s), sinon fallback en échantillonnant les trades.
        """
        import httpx

        normalized_symbol = symbol.replace("/", "")
        rest_url = f"http://{self.host}:9000/exec"

        def _map_rows(data) -> list[dict]:
            cols = [c["name"] for c in data["columns"]]
            candles = []
            for row in reversed(data["dataset"]):  # dataset est DESC
                row_dict = dict(zip(cols, row))
                ts_val = row_dict["timestamp"]
                ts_ms = 0
                if isinstance(ts_val, str):
                    from datetime import datetime
                    try:
                        dt = datetime.fromisoformat(ts_val.replace('Z', '+00:00'))
                        ts_ms = int(dt.timestamp() * 1000)
                    except Exception:
                        pass
                elif isinstance(ts_val, (int, float)):
                    ts_ms = int(ts_val / 1000)

                candles.append({
                    "symbol": row_dict.get("symbol", normalized_symbol),
                    "timestamp": ts_ms,
                    "open": float(row_dict["open"]),
                    "high": float(row_dict["high"]),
                    "low": float(row_dict["low"]),
                    "close": float(row_dict["close"]),
                    "volume": float(row_dict["volume"])
                })
            return candles

        async def _exec_query(client: httpx.AsyncClient, query: str) -> list[dict]:
            resp = await client.get(rest_url, params={"query": query})
            resp.raise_for_status()
            data = resp.json()
            if not data.get("dataset"):
                return []
            return _map_rows(data)

        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                # 1) Tentative sur la table de bougies (si alimentée)
                query_candles = (
                    f"SELECT * FROM candles_1s "
                    f"WHERE symbol='{normalized_symbol}' "
                    f"ORDER BY timestamp DESC LIMIT {limit}"
                )
                candles = await _exec_query(client, query_candles)
                if candles:
                    return candles

                # 2) Fallback: reconstituer des bougies à partir des trades
                query_trades = (
                    "SELECT timestamp, "
                    "first(price) AS open, "
                    "max(price) AS high, "
                    "min(price) AS low, "
                    "last(price) AS close, "
                    "sum(qty) AS volume "
                    f"FROM trades WHERE symbol='{normalized_symbol}' "
                    "SAMPLE BY 1s ALIGN TO CALENDAR "
                    "ORDER BY timestamp DESC "
                    f"LIMIT {limit}"
                )
                return await _exec_query(client, query_trades)

        except Exception as e:
            logger.warning(f"⚠️ Impossible de charger l'historique pour {symbol} depuis QuestDB: {e}")
            return []
