import asyncio
import httpx
import json
from typing import List, Any
import logging

# Gestion gracieuse de l'absence de FastAPI pour les scripts de backtest
try:
    from fastapi import WebSocket
except ImportError:
    WebSocket = Any

API_URL = "http://localhost:8000"

class LogManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LogManager, cls).__new__(cls)
            cls._instance.active_connections = []
        return cls._instance

    async def connect(self, websocket: Any):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: Any):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        if not self.active_connections:
            return
            
        # Copie de la liste pour éviter les problèmes de modification pendant l'itération
        for connection in list(self.active_connections):
            try:
                # Vérification défensive de l'état
                if hasattr(connection, "client_state") and connection.client_state.value == 1:
                    await connection.send_text(message)
                elif not hasattr(connection, "client_state"):
                    # Fallback si l'objet n'a pas client_state (ex: mock ou version différente)
                    await connection.send_text(message)
                else:
                    self.disconnect(connection)
            except Exception as e:
                print(f"⚠️ Erreur Broadcast (Ignorée): {e}")
                self.disconnect(connection)

    async def broadcast_event(self, event_type: str, data: dict):
        """
        Diffuse un événement structuré JSON.
        """
        payload = {"type": event_type, **data}
        message = json.dumps(payload)
        await self.broadcast(message)

log_manager = LogManager()

async def broadcast_log(message: str):
    """
    Diffuse un log.
    - Si nous sommes le serveur (connexions actives), on diffuse via WebSocket.
    - Si nous sommes le bot (pas de connexions), on envoie au serveur via HTTP.
    """
    if log_manager.active_connections:
        await log_manager.broadcast(message)
    else:
        # Fallback: Envoi au serveur API si on est dans un processus séparé (ex: main.py)
        try:
            async with httpx.AsyncClient() as client:
                # On envoie un JSON avec le champ "message"
                # Le serveur attend un LogMessage(message: str) ou un dict générique
                # Le endpoint /internal/broadcast attend un Dict[str, Any]
                # Si on veut que ça apparaisse comme un log dans l'UI, il faut que le type soit "log"
                # Le serveur fait: await log_manager.broadcast(json.dumps(payload))
                # L'UI attend: if msg_type == "log" ... txt = data.get("message")
                
                payload = {
                    "type": "log",
                    "message": message
                }
                await client.post(f"{API_URL}/internal/broadcast", json=payload, timeout=1.0)
        except Exception:
            # Si le serveur est éteint, on ignore silencieusement pour ne pas bloquer le bot
            pass

class BroadcastLogHandler(logging.Handler):
    """Handler de logs qui diffuse via WebSocket/HTTP"""
    def emit(self, record):
        try:
            msg = self.format(record)
            # On tente de récupérer la boucle courante pour envoyer en async
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    loop.create_task(broadcast_log(msg))
            except RuntimeError:
                pass # Pas de boucle active
        except Exception:
            self.handleError(record)
