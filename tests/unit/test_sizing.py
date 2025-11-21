from core.sizing import size_from_risk
from interfaces.exchange import MarketRules

def test_size_from_risk_basic():
    rules = MarketRules(symbol="BTCUSDT", base="BTC", quote="USDT", tick_size=0.1, step_size=0.001, min_qty=0.001, min_notional=5)
    qty = size_from_risk(100, entry=30000, stop=29900, rules=rules)
    assert qty > 0

def test_size_respects_min_notional():
    rules = MarketRules(symbol="BTCUSDT", base="BTC", quote="USDT", tick_size=0.1, step_size=0.001, min_qty=0.001, min_notional=100)
    qty = size_from_risk(10, entry=30000, stop=29900, rules=rules)
    assert qty == 0.0
