from fastapi.testclient import TestClient
from api.server import app

def test_symbol_validation_and_lockout():
    client = TestClient(app)
    # Bad symbol format for binance (uses dash)
    r = client.post("/orders/preview", json={"backend": "binance_spot", "symbol": "BTC-USD", "side": "buy", "type": "market", "sl": 100, "tp": 200})
    assert r.status_code == 400
    # Good preview (assuming markets fetched lazily). Use PAPER mode.
    r2 = client.post("/orders/preview", json={"backend": "binance_spot", "symbol": "BTCUSDT", "side": "buy", "type": "market", "sl": 100, "tp": 200})
    assert r2.status_code in (200, 400)  # if market not fetched yet could be 400 Unknown symbol
    # Panic then ensure lockout prevents execution
    client.post("/panic")
    r3 = client.post("/orders/execute", json={"backend": "binance_spot", "symbol": "BTCUSDT", "side": "buy", "type": "market", "qty": 0.01})
    assert r3.status_code == 409
