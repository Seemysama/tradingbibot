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

class BroadcastLogHandler(logging.Handler):
    """
    Handler de logs custom qui envoie les logs vers l'API via HTTP POST.
    Utilisé pour afficher les logs dans l'interface graphique.
    """
    def emit(self, record):
        try:
            log_entry = self.format(record)
            # On utilise httpx en mode "fire and forget" (asyncio.create_task)
            # pour ne pas bloquer le thread principal du bot
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    loop.create_task(self._send_log(log_entry))
            except RuntimeError:
                # Pas de boucle d'événements active (ex: démarrage)
                pass
        except Exception:
            self.handleError(record)

    async def _send_log(self, message: str):
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                await client.post(f"{API_URL}/logs", json={"message": message})
        except Exception:
            # On ignore les erreurs de connexion à l'API pour ne pas crasher le bot
            pass

async def broadcast_event(event_type: str, data: dict):
    """
    Envoie un événement structuré (JSON) au serveur API pour diffusion WebSocket.
    """
    try:
        payload = {
            "type": event_type,
            "data": data,
            "timestamp": int(asyncio.get_event_loop().time() * 1000)
        }
        async with httpx.AsyncClient(timeout=0.5) as client:
            await client.post(f"{API_URL}/events", json=payload)
    except Exception as e:
        # Fail silently pour ne pas bloquer le trading
        pass
