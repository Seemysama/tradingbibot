"""WebSocket abstraction placeholder.

Future implementation: unified async generators for ticker & OHLC using either
ccxt.pro (if installed & licensed) or native websockets (aiohttp/websockets).
"""
from __future__ import annotations
from typing import AsyncIterator, Callable, Awaitable

class WSClient:
    def __init__(self) -> None:
        self._connected = False

    async def connect(self) -> None:  # type: ignore[no-untyped-def]
        self._connected = True

    async def close(self) -> None:  # type: ignore[no-untyped-def]
        self._connected = False

    async def ticker(self, symbol: str) -> AsyncIterator[dict]:  # pragma: no cover - placeholder
        raise NotImplementedError

    async def ohlc(self, symbol: str, tf: str) -> AsyncIterator[dict]:  # pragma: no cover
        raise NotImplementedError