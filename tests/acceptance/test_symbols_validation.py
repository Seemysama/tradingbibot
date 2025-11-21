from fastapi.testclient import TestClient
from api.server import app, _loaded_adapters  # type: ignore
import pytest
from interfaces.exchange import ExchangeAdapter, MarketRules, OrderReq, Preview, Placed
from typing import Optional

class MinimalAdapter(ExchangeAdapter):  # type: ignore[misc]
    def __init__(self) -> None:
        self.markets = {"BTCUSDT": MarketRules(symbol="BTCUSDT", base="BTC", quote="USDT", tick_size=0.1, step_size=0.001, min_qty=0.001, min_notional=5)}
    async def connect(self): ...  # type: ignore[no-untyped-def]
    async def fetch_markets(self): return list(self.markets.values())  # type: ignore[no-untyped-def]
    async def watch_ohlc(self, symbol: str, tf: str): raise NotImplementedError  # type: ignore[no-untyped-def]
    async def watch_ticker(self, symbol: str): raise NotImplementedError  # type: ignore[no-untyped-def]
    async def preview(self, req: OrderReq) -> Preview: return Preview(symbol=req.symbol, side=req.side, qty=1, est_max_loss=10, rr=2, sl=req.sl or 0, tp=req.tp or 0)
    async def place(self, req: OrderReq) -> Placed: return Placed(order_id="SIM")
    async def cancel_all(self, symbol: Optional[str] = None): ...  # type: ignore[no-untyped-def]
    async def positions(self): return []  # type: ignore[no-untyped-def]


@pytest.fixture(autouse=True)
def inject():  # type: ignore[no-untyped-def]
    _loaded_adapters["binance_spot"] = MinimalAdapter()


def test_symbol_known():
    c = TestClient(app)
    r = c.post("/orders/preview", json={"backend": "binance_spot", "symbol": "BTCUSDT", "side": "buy", "type": "market", "qty": 1})
    assert r.status_code == 200

def test_symbol_unknown():
    c = TestClient(app)
    r = c.post("/orders/preview", json={"backend": "binance_spot", "symbol": "FOO", "side": "buy", "type": "market", "qty": 1})
    assert r.status_code == 400