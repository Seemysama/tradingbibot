from __future__ import annotations
from typing import Protocol, AsyncIterator, Optional
from pydantic import BaseModel

class Bar(BaseModel):
    ts: int; o: float; h: float; l: float; c: float; v: float

class Ticker(BaseModel):
    ts: int; bid: Optional[float]=None; ask: Optional[float]=None; last: Optional[float]=None

class MarketRules(BaseModel):
    symbol: str; base: str; quote: str
    tick_size: float; step_size: float
    min_qty: float; min_notional: float

class OrderReq(BaseModel):
    symbol: str; side: str  # 'buy'|'sell'
    type: str   # 'market'|'limit'
    qty: float
    price: float | None = None
    sl: float | None = None
    tp: float | None = None
    leverage: int | None = None

class Preview(BaseModel):
    symbol: str; side: str; qty: float; sl: float; tp: float
    est_max_loss: float; rr: float

class Placed(BaseModel):
    order_id: str
    client_oid: str | None = None

class ExchangeAdapter(Protocol):
    async def connect(self) -> None: ...
    async def fetch_markets(self) -> list[MarketRules]: ...
    async def watch_ohlc(self, symbol: str, tf: str) -> AsyncIterator[Bar]: ...
    async def watch_ticker(self, symbol: str) -> AsyncIterator[Ticker]: ...
    async def preview(self, req: OrderReq) -> Preview: ...
    async def place(self, req: OrderReq) -> Placed: ...
    async def cancel_all(self, symbol: str | None = None) -> None: ...
    async def positions(self) -> list[dict]: ...
