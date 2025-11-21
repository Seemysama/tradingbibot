# 🚀 TradingBiBot - Multi-Exchange Trading System

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-Latest-green.svg)](https://fastapi.tiangolo.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-Latest-red.svg)](https://streamlit.io)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Un système de trading automatisé moderne supportant **Binance**, **Coinbase** et **Kraken** avec interface web interactive et API REST complète.

## Features
- Multi-exchange adapters (symbol validation via official listings)
- Risk-first: mandatory SL/TP in preview, RiskGuard (daily DD, per-trade risk, panic lockout)
- Idempotent order routing
- SQLite persistence (TODO)
- Web UI (preview / execute / panic)

## Stack
Python 3.11, FastAPI, Streamlit, CCXT / native REST, SQLAlchemy, Pydantic v2, Ruff, mypy --strict, pytest.

## Quick Start
```bash
make install
cp .env.example .env  # fill keys
make api  # starts uvicorn
make ui   # starts streamlit UI
```

## Official Symbol Listings
- Binance Spot: GET https://api.binance.com/api/v3/exchangeInfo -> symbols[].symbol (exclude status != TRADING)
- Coinbase Advanced: GET https://api.coinbase.com/api/v3/brokerage/products -> product_id
- Kraken: GET https://api.kraken.com/0/public/AssetPairs -> result keys (map altname / wsname)

Always validate user-entered symbol against the fetched list before trading.

## Sandbox / Test
- Binance Testnet (Spot): https://testnet.binance.vision (adjust BINANCE_REST + key pair)
- Coinbase Advanced Sandbox: https://api-sandbox.coinbase.com/api/v3/brokerage
- Kraken: No full sandbox; use small sizes and PAPER mode.

## Compliance / Restrictions
- Binance Futures endpoints (fapi*) strictly forbidden (jurisdiction FR)
- Kraken margin limited to leverage <=5.

## RiskGuard
Configuration via environment or code (risk_per_trade, daily_dd_max, etc.). Panic endpoint triggers lockout and attempts to cancel all.

## Tests
Run `make test`.
(Planned) Acceptance tests assert:
1. Symbols existence via listing endpoints.
2. Preview risk calculations.
3. Execution order id presence.
4. Risk lockout (HTTP 409) once DD reached.
5. Panic: lockout + positions flattened.

## Roadmap
- Implement Coinbase & Kraken adapters (JWT, leverage & close conditions)
- Implement WebSocket streaming abstraction
- Persist orders/trades/equity in SQLite
- Add structured logging + audit journal
- Add acceptance test suite with HTTPX AsyncClient

## Security Notes
- Never log raw secrets.
- Validate symbols every run; refuse unknown.
- Respect rate limits (429 -> exponential backoff).

## Disclaimer
Educational tool. Not investment advice. Use at your own risk.

## Environment Flags
| Variable | Effet | Défaut |
|----------|-------|--------|
| REAL_ADAPTERS | Active appels réels (bootstrap marchés) pour adapters. Sans cela tout est simulé. | 0 |
| OFFLINE_RULES | Si 1, évite re-fetch des listes marchés et utilise cache symboles. | 0 |
| MARKETS_WARMUP | Si 1, précharge les marchés au démarrage (peut ralentir le boot). | 0 |
| LOCKOUT_TTL_SECONDS | Lockout automatique se désactive après TTL (RiskGuard). | 0 (illimité) |
| LOG_JSON | Journaux middleware HTTP en JSON si true. | false |

## Rate Limiting Interne
Un rate limiter token-bucket léger (`core.ratelimit.RateLimiter`) protège:
- Bootstrap Binance (2 coups init, refill 0.2/s)
- Placements simulés Binance (5 req/s)

Adaptable: remplacer dans chaque adapter par des limites spécifiques échange.

## Symboles & Validation
`core.symbols` fournit:
- `normalize(exchange, symbol)`
- `validate_symbol(exchange, symbol, markets?) -> bool`
- `validate_symbol_info(exchange, symbol) -> (bool, message)`
Exemples attendus: binance_spot=BTCUSDT, coinbase_advanced=BTC-USD, kraken_margin=XBTUSD.

## Adapter Injection Tests
Les tests peuvent monkeypatcher `_loaded_adapters` (exporté par `api.server`) ou utiliser `get_adapter(name)`.
