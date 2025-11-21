from __future__ import annotations
"""Order routing with idempotence and retries + adapter registry."""
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Awaitable, Dict, Optional
from tenacity import retry, stop_after_attempt, wait_exponential
from interfaces.exchange import ExchangeAdapter

# Registre global d'adapters pour tests
_loaded_adapters: Dict[str, ExchangeAdapter] = {}

def register(name: str, adapter: ExchangeAdapter) -> None:
    """Enregistre un adapter dans le registre global."""
    _loaded_adapters[name] = adapter

def get_adapter(name: Optional[str]) -> Optional[ExchangeAdapter]:
    """Récupère un adapter par nom."""
    if name is None:
        return None
    return _loaded_adapters.get(name)

def list_adapters() -> Dict[str, ExchangeAdapter]:
    """Liste tous les adapters enregistrés."""
    return dict(_loaded_adapters)

@dataclass(frozen=True)
class Decision:
    symbol: str
    side: str
    type: str
    qty: float
    price: float | None
    sl: float | None
    tp: float | None

    def fingerprint(self) -> str:
        payload = json.dumps(self.__dict__, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

class OrderRouter:
    def __init__(self) -> None:
        self._executed: set[str] = set()

    async def route(self, decision: Decision, executor: Callable[[], Awaitable[Any]]) -> Any:
        fp = decision.fingerprint()
        if fp in self._executed:
            return {"status": "duplicate", "fingerprint": fp}
        result = await self._execute_with_retry(executor)
        self._executed.add(fp)
        return result

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5))
    async def _execute_with_retry(self, executor: Callable[[], Awaitable[Any]]):  # type: ignore[no-untyped-def]
        return await executor()
