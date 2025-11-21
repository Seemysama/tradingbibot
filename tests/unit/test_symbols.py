from core.symbols import normalize, validate_symbol, expected_example
from interfaces.exchange import MarketRules

def test_normalize_variants():
    assert normalize("binance_spot", "btcusdt") == "BTCUSDT"
    assert normalize("kraken_margin", "BTCUSD") == "XBTUSD"

def test_validate_symbol():
    markets = [MarketRules(symbol="BTCUSDT", base="BTC", quote="USDT", tick_size=0.01, step_size=0.001, min_qty=0.001, min_notional=5)]
    assert validate_symbol("binance_spot", "BTCUSDT", markets)
    assert not validate_symbol("binance_spot", "ETHBTC", markets)

def test_expected_example():
    assert expected_example("coinbase_advanced") == "BTC-USD"
