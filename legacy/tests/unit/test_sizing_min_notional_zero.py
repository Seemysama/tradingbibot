from interfaces.exchange import MarketRules
from core.sizing import size_from_risk

def test_sizing_min_notional_zero():
    rules = MarketRules(symbol="BTCUSDT", base="BTC", quote="USDT", tick_size=0.1, step_size=0.001, min_qty=0.001, min_notional=100)
    # risk amount 50 < min_notional => retourne 0
    qty = size_from_risk(50, entry=30000, stop=29900, rules=rules)
    assert qty == 0.0
