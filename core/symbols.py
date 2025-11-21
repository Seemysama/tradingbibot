from __future__ import annotations
"""Symbol normalization & validation (stateless) - realistic validation."""
from typing import Iterable, Any, Set, Dict, Tuple, Optional
import time, os, re

# Patterns réalistes pour validation
_BINANCE_RE = re.compile(r"^[A-Z0-9]{5,20}$")
_CB_RE = re.compile(r"^[A-Z0-9]+-[A-Z0-9]+$")
_KRAKEN_SEP = re.compile(r"[^A-Za-z0-9]+")

_TTL_SECONDS = 600  # 10 min
_cached_symbols: Dict[Tuple[str, int], Set[str]] = {}

def _cache_key(exchange: str) -> Tuple[str, int]:
    bucket = int(time.time() // _TTL_SECONDS)
    return (exchange.lower(), bucket)

def _symbols_from_markets(markets: Iterable[Any]) -> Set[str]:
    out: Set[str] = set()
    for m in markets:
        sym = getattr(m, "symbol", None)
        if sym:
            out.add(str(sym).upper())
    return out

def validation_error_message(exchange: str, symbol: str) -> str:
    example = expected_example(exchange)
    return f"Invalid symbol '{symbol}' for {exchange}. Example: {example}" if example else f"Invalid symbol '{symbol}' for {exchange}."

def cache_symbols(exchange: str, markets: Iterable[Any]) -> None:
    _cached_symbols[_cache_key(exchange)] = _symbols_from_markets(markets)

def cached_symbols(exchange: str) -> Set[str]:
    ex = exchange.lower()
    current_bucket = _cache_key(exchange)[1]
    for (e, b), syms in sorted(_cached_symbols.items(), key=lambda x: x[0][1], reverse=True):
        if e == ex and b <= current_bucket:
            return syms
    return set()

def normalize(exchange: str, symbol: str) -> str:
    s = symbol.upper()
    if exchange == "binance_spot":
        return s.replace("-", "")
    if exchange == "coinbase_advanced":
        return s if "-" in s else s[:3] + "-" + s[3:]
    if exchange == "kraken_margin":
        if s.startswith("BTC"):
            return s.replace("BTC", "XBT")
        return s
    return s

def validate_symbol_simple(symbol: str, backend: str) -> bool:
    """Simple validation per super prompt specifications."""
    norm = normalize(backend, symbol)
    if backend == "binance_spot":
        return norm.endswith("USDT")
    if backend == "coinbase_advanced":
        return "-" in norm
    if backend == "kraken_margin":
        return norm in {"XBTUSD","ETHUSD"}
    return False

def expected_example(exchange: str) -> str:
    return {
        "binance_spot": "BTCUSDT",
        "coinbase_advanced": "BTC-USD",
        "kraken_margin": "XBTUSD",
    }.get(exchange, "BTCUSDT")

def validate_symbol_info(exchange: str, symbol: str, markets: Optional[Iterable[Any]] = None) -> Tuple[bool, str]:
    """Validation stricte avec patterns réalistes - retourne (bool, message)."""
    # D'abord validation du format selon l'exchange
    if exchange == "binance_spot":
        if "-" in symbol or not _BINANCE_RE.match(symbol):
            return False, "Binance expects symbols like BTCUSDT (uppercase, no dash)"
    elif exchange == "coinbase_advanced":
        if not _CB_RE.match(symbol):
            return False, "Coinbase expects product ids like BTC-USD"
    elif exchange == "kraken_margin":
        s = _KRAKEN_SEP.sub("", symbol).replace("BTC", "XBT")
        if len(s) < 6:
            return False, "Kraken expects altnames like XBTUSD"
    else:
        return False, validation_error_message(exchange, symbol)
    
    # Puis validation de l'existence dans les marchés fournis
    norm = normalize(exchange, symbol)
    symbols_set: Set[str] = set()
    if markets is not None and os.getenv("OFFLINE_RULES", "0") != "1":
        symbols_set = _symbols_from_markets(markets)
        if symbols_set:
            cache_symbols(exchange, markets)
    if not symbols_set:
        symbols_set = cached_symbols(exchange)
    
    if symbols_set:
        if norm not in symbols_set:
            return False, validation_error_message(exchange, symbol)
    
    return True, ""

def validate_symbol(exchange: str, symbol: str, markets: Optional[Iterable[Any]] = None) -> bool:
    """Validation stricte avec patterns réalistes - maintient compatibilité API booléenne."""
    valid, _ = validate_symbol_info(exchange, symbol, markets)
    return valid

__all__ = [
    "normalize",
    "validate_symbol",
    "validate_symbol_info",
    "expected_example",
    "validation_error_message",
]
