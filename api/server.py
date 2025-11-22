from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
from src.utils import LogManager
import asyncio
from typing import Optional, Dict, Any

app = FastAPI()
log_manager = LogManager()

# --- Modèles de Données ---
class LogMessage(BaseModel):
    message: str

class BroadcastMessage(BaseModel):
    type: str
    data: Dict[str, Any]

class OrderRequest(BaseModel):
    symbol: str
    side: str
    qty: float
    price: Optional[float] = None
    type: str = "MARKET"

# --- État Partagé (Simulation pour l'instant, à connecter au vrai moteur plus tard) ---
# Dans une architecture idéale, le serveur API communiquerait avec le moteur via Redis ou ZMQ.
# Ici, pour simplifier, on va juste broadcaster les commandes comme des logs "spéciaux"
# que le bot pourrait écouter, ou simuler l'action.

@app.post("/internal/broadcast")
async def broadcast_log_internal(payload: Dict[str, Any]):
    """
    Endpoint interne générique.
    Accepte tout JSON et le diffuse tel quel aux clients WebSocket.
    """
    # On convertit le dict en string JSON pour le transport WebSocket
    import json
    await log_manager.broadcast(json.dumps(payload))
    return {"status": "ok"}

@app.post("/orders/execute")
async def execute_order(order: OrderRequest):
    """Reçoit un ordre manuel depuis l'UI et le diffuse."""
    try:
        log_msg = f"⚠️ ORDRE MANUEL REÇU: {order.side} {order.qty} {order.symbol} ({order.type})"
        # On lance le broadcast en tâche de fond pour ne pas bloquer la réponse HTTP
        asyncio.create_task(log_manager.broadcast(log_msg))
    except Exception as e:
        print(f"❌ Erreur execute_order: {e}")
    
    return {"status": "received", "order": order}

@app.post("/panic")
async def panic_mode():
    """Déclenche le mode panique."""
    log_msg = "🚨 PANIC MODE ACTIVÉ PAR L'UTILISATEUR !"
    await log_manager.broadcast(log_msg)
    # TODO: Implémenter la logique d'arrêt d'urgence
    return {"status": "panic_activated"}

@app.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    await log_manager.connect(websocket)
    try:
        while True:
            # Garder la connexion active
            data = await websocket.receive_text()
            # Si on reçoit un ping, on ne fait rien (ça maintient juste la connexion)
            if data == "ping":
                pass
    except WebSocketDisconnect:
        log_manager.disconnect(websocket)
    except Exception as e:
        print(f"Erreur WebSocket: {e}") # Log serveur
        log_manager.disconnect(websocket)
