import pytest
from fastapi.testclient import TestClient
from api.server import app, _loaded_adapters  # type: ignore
from interfaces.exchange import ExchangeAdapter, MarketRules, OrderReq, Preview, Placed
from typing import Optional


class FakeAdapter(ExchangeAdapter):  # type: ignore[misc]
    def __init__(self) -> None:
        self.markets = {"BTCUSDT": MarketRules(symbol="BTCUSDT", base="BTC", quote="USDT", tick_size=0.1, step_size=0.001, min_qty=0.001, min_notional=5)}

    async def connect(self) -> None:  # pragma: no cover
        return None

    async def fetch_markets(self):  # type: ignore[no-untyped-def]
        return list(self.markets.values())

    async def watch_ohlc(self, symbol: str, tf: str):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def watch_ticker(self, symbol: str):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def preview(self, req: OrderReq) -> Preview:
        return Preview(symbol=req.symbol, side=req.side, qty=0.01, est_max_loss=10.0, rr=2.0, sl=req.sl or 0.0, tp=req.tp or 0.0)

    async def place(self, req: OrderReq) -> Placed:
        return Placed(order_id="SIM-TEST")

    async def cancel_all(self, symbol: Optional[str] = None) -> None:
        return None

    async def positions(self):  # type: ignore[no-untyped-def]
        return []


@pytest.fixture(autouse=True)
def inject_fake_adapter(monkeypatch):  # type: ignore[no-untyped-def]
    _loaded_adapters["binance_spot"] = FakeAdapter()


def test_preview_and_execute_flow():
    client = TestClient(app)
    pv = client.post("/orders/preview", json={"backend": "binance_spot", "symbol": "BTCUSDT", "side": "buy", "type": "market", "sl": 29000, "tp": 31000}).json()
    assert pv["qty"] == 0.01
    ex = client.post("/orders/execute", json={"backend": "binance_spot", "symbol": "BTCUSDT", "side": "buy", "type": "market", "qty": 0.01}).json()
    assert ex["order_id"].startswith("SIM")

def test_panic_sets_lockout():
    client = TestClient(app)
    resp = client.post("/panic").json()
    assert resp["lockout"] is True
    locked = client.post("/orders/execute", json={"backend": "binance_spot", "symbol": "BTCUSDT", "side": "buy", "type": "market", "qty": 0.01})
    assert locked.status_code == 409
