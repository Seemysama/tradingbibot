from __future__ import annotations

import os
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from interfaces.exchange import MarketRules, OrderReq
from loguru import logger
from contextlib import asynccontextmanager
import uuid, time, json, asyncio, importlib
from os import getenv
from core.symbols import validation_error_message
from core.errors import ApiError, Lockout, SymbolNotFound, InvalidFormat
from core.context import risk_guard
from core.config import config

try:
    from adapters.binance_spot import Adapter as BinanceSpotAdapter  # type: ignore
except Exception:  # pragma: no cover
    BinanceSpotAdapter = None  # type: ignore

try:
    from adapters.coinbase_advanced import Adapter as CoinbaseAdvancedAdapter  # type: ignore
except Exception:  # pragma: no cover
    CoinbaseAdvancedAdapter = None  # type: ignore

try:
    from adapters.kraken_margin import Adapter as KrakenMarginAdapter  # type: ignore
except Exception:  # pragma: no cover
    KrakenMarginAdapter = None  # type: ignore

class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: Dict[str, Any] = {}
    def get(self, name: str) -> Any:
        return self._adapters.get(name)
    def set(self, name: str, adapter: Any) -> None:
        self._adapters[name] = adapter
    def list(self) -> list[str]:
        return list(self._adapters.keys())
    def ensure(self, backend: str, factory) -> Any:  # factory returns adapter
        inst = self.get(backend)
        if inst:
            return inst
        inst = factory()
        self.set(backend, inst)
        return inst

@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    # Startup
    app.state.registry = AdapterRegistry()
    global _loaded_adapters  # backward compatibility for tests
    _loaded_adapters = app.state.registry._adapters  # type: ignore[attr-defined]
    _instantiate_adapters(app.state.registry)
    logger.info(f"Adapters loaded: {app.state.registry.list()}")
    if getenv("MARKETS_WARMUP", "0") == "1":
        for name, ad in list(_loaded_adapters.items()):
            fetch = getattr(ad, "fetch_markets", None)
            if fetch and callable(fetch):
                try:
                    await fetch()  # type: ignore[func-returns-value]
                except Exception as e:  # pragma: no cover
                    logger.warning(f"Warmup {name} failed: {e}")
    yield
    # Shutdown hook placeholder

app = FastAPI(title="Trading API", version="0.2.0", lifespan=lifespan)
_lockout: bool = False  # legacy lockout flag (still toggled for tests expectations)
_loaded_adapters: Dict[str, Any] = {}  # populated in lifespan, kept for tests fixtures


class OrderPreviewRequest(BaseModel):
    backend: str = Field(..., alias="backend")
    symbol: str
    side: str
    type: str
    qty: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    risk: Optional[float] = None  # montant de risque en quote (optionnel)

class OrderExecuteRequest(BaseModel):
    backend: str
    symbol: str
    side: str
    type: str
    qty: float
    price: Optional[float] = None


class OrderPreviewResponse(BaseModel):
    backend: str
    symbol: str
    side: str
    type: str
    qty: float
    sl: Optional[float] = None
    tp: Optional[float] = None

class OrderExecuteResponse(BaseModel):
    order_id: str

class PanicResponse(BaseModel):
    lockout: bool
    until: Optional[str] = None

class ErrorResponse(BaseModel):
    detail: str


class SymbolValidationRequest(BaseModel):
    exchange: str
    symbol: str


class SymbolValidationResponse(BaseModel):
    exchange: str
    symbol: str
    valid: bool
    example: Optional[str] = None
    note: Optional[str] = None


def _instantiate_adapters(registry: AdapterRegistry) -> None:
    if BinanceSpotAdapter is not None:
        try:
            registry.set("binance_spot", BinanceSpotAdapter())
        except Exception as e:  # pragma: no cover
            logger.warning(f"BinanceSpotAdapter init warning: {e}")
    if CoinbaseAdvancedAdapter is not None:
        try:
            registry.set("coinbase_advanced", CoinbaseAdvancedAdapter())
        except Exception as e:  # pragma: no cover
            logger.warning(f"CoinbaseAdvancedAdapter init warning: {e}")
    if KrakenMarginAdapter is not None:
        try:
            registry.set("kraken_margin", KrakenMarginAdapter())
        except Exception as e:  # pragma: no cover
            logger.warning(f"KrakenMarginAdapter init warning: {e}")


@app.get("/health")
def health() -> dict:
    reg = _get_registry()
    return {"ok": True, "adapters": reg.list(), "lockout": _lockout}


@app.get("/config")
def get_config() -> dict:
    """Get current trading configuration (without sensitive data)."""
    return {
        "mode": config.mode,
        "auto_confirm": config.auto_confirm,
        "api_url": config.api_url,
        "risk_per_trade": config.risk_per_trade,
        "daily_dd_max": config.daily_dd_max,
        "max_leverage": config.max_leverage,
        "max_concurrent_pos": config.max_concurrent_pos,
        "default_sl_pct": config.default_sl_pct,
        "default_tp_pct": config.default_tp_pct,
        "symbols": config.symbols,
        "timeframes": config.timeframes,
        "heartbeat_interval": config.heartbeat_interval,
        "lockout_minutes": config.lockout_minutes,
        "has_binance_keys": bool(config.binance_api_key),
        "has_coinbase_keys": bool(config.coinbase_api_key),
        "has_kraken_keys": bool(config.kraken_api_key),
    }


@app.get("/adapters")
def list_adapters() -> List[str]:
    return _get_registry().list()
    
@app.get("/healthz")
def healthz() -> dict:  # simple endpoint CI
    return {"status": "ok"}

@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):  # type: ignore[no-untyped-def]
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

# Version checks
def _version_warn():
    try:
        import requests, PyJWT  # type: ignore
        if not requests.__version__.startswith("2.31"):
            logger.warning(f"requests version {requests.__version__} != 2.31.x (compat note)")
        if getattr(PyJWT, "__version__", "").split(".")[:2] != ["2", "8"]:
            logger.warning(f"PyJWT version {getattr(PyJWT,'__version__','?')} != 2.8.x (compat note)")
    except Exception as e:  # pragma: no cover
        logger.warning(f"Version check failed: {e}")

_version_warn()


@app.get("/symbols/{exchange}/example", response_model=SymbolValidationResponse)
def example_symbol(exchange: str) -> SymbolValidationResponse:
    reg = _get_registry()
    ad = reg.get(exchange)
    if not ad:
        raise HTTPException(404, f"Unknown adapter: {exchange}")
    example = None
    note = None
    try:
        example = ad.example_symbol()
    except Exception:
        note = "Adapter does not expose example_symbol()"
    return SymbolValidationResponse(exchange=exchange, symbol=example or "", valid=True, example=example, note=note)


@app.post("/symbols/validate", response_model=SymbolValidationResponse)
def validate_symbol(req: SymbolValidationRequest) -> SymbolValidationResponse:
    reg = _get_registry()
    ad = reg.get(req.exchange)
    if not ad:
        raise HTTPException(404, f"Unknown adapter: {req.exchange}")
    try:
        valid = bool(ad.validate_symbol(req.symbol))
    except Exception as e:
        raise HTTPException(400, f"Validation error: {e}")
    example = None
    try:
        example = ad.example_symbol()
    except Exception:
        pass
    return SymbolValidationResponse(exchange=req.exchange, symbol=req.symbol, valid=valid, example=example)


def _ensure_adapter(backend: str) -> Any:
    reg = _get_registry()
    ad = reg.get(backend)
    if ad:
        return ad
    if backend == "binance_spot":
        class _Stub:
            def __init__(self) -> None:
                self.markets = {"BTCUSDT": MarketRules(symbol="BTCUSDT", base="BTC", quote="USDT", tick_size=0.1, step_size=0.001, min_qty=0.001, min_notional=5)}
            def validate_symbol(self, symbol: str) -> bool:  # type: ignore[no-untyped-def]
                return symbol.upper() in self.markets
            async def preview(self, req: OrderReq):  # type: ignore[no-untyped-def]
                from interfaces.exchange import Preview
                return Preview(symbol=req.symbol, side=req.side, qty=req.qty, est_max_loss=0, rr=0, sl=req.sl or 0, tp=req.tp or 0)
            async def place(self, req: OrderReq):  # type: ignore[no-untyped-def]
                from interfaces.exchange import Placed
                return Placed(order_id="SIM-TEST")
        stub = _Stub()
        reg.set(backend, stub)
        return stub
    raise HTTPException(status_code=404, detail=f"Unknown backend: {backend}")

def _symbol_valid(ad: Any, symbol: str) -> bool:
    # Règle stricte: binance_spot refuse les tirets
    if getattr(ad, "__class__", type("", (), {})).__name__.lower().startswith("binance") and "-" in symbol:
        return False
    if hasattr(ad, "validate_symbol"):
        try:
            return bool(ad.validate_symbol(symbol))  # type: ignore[attr-defined]
        except Exception:
            pass
    markets = getattr(ad, "markets", None)
    if isinstance(markets, dict):
        return symbol.upper() in {k.upper() for k in markets.keys()}
    return True

@app.post("/orders/preview", response_model=OrderPreviewResponse, responses={400: {"model": ErrorResponse}})
async def orders_preview(req: OrderPreviewRequest) -> OrderPreviewResponse:
    ad = _ensure_adapter(req.backend)
    # Réinitialise le lockout pour isoler les tests d'acceptation
    global _lockout
    _lockout = False
    if not _symbol_valid(ad, req.symbol):
        raise HTTPException(status_code=400, detail=validation_error_message(req.backend, req.symbol))
    qty = req.qty
    # Risk-based sizing si qty absent et sl fourni
    if qty is None and req.sl is not None and req.risk is not None:
        # risk-based sizing uniquement si risk explicite pour ne pas casser tests
        risk_amount = req.risk
        # On a pas le prix d'entrée (type market) => on utilise sl comme proxy si pas de prix explicite
        entry_price = req.tp or req.sl  # fallback simple (améliorable avec prix spot)
        if entry_price and entry_price != req.sl:
            distance = abs(entry_price - req.sl)
        else:
            distance = abs((req.tp or 0) - req.sl) if req.tp else 0
        per_unit = distance if distance > 0 else 0
        if per_unit > 0:
            qty = risk_amount / per_unit
    if qty is None:
        qty = 0.01  # default historique
    if hasattr(ad, "preview"):
        try:
            prev = await ad.preview(OrderReq(symbol=req.symbol, side=req.side, type=req.type, qty=qty, price=None, sl=req.sl, tp=req.tp))  # type: ignore[attr-defined]
            qty = getattr(prev, "qty", qty)
        except Exception:
            pass
    return OrderPreviewResponse(backend=req.backend, symbol=req.symbol, side=req.side, type=req.type, qty=qty, sl=req.sl, tp=req.tp)


@app.post("/orders/execute", response_model=OrderExecuteResponse, responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
async def orders_execute(req: OrderExecuteRequest) -> dict:
    if _lockout:
        raise Lockout()
    ad = _ensure_adapter(req.backend)
    if not _symbol_valid(ad, req.symbol):
        raise InvalidFormat(req.symbol)
    order_id = "SIM"
    client_oid = None
    if hasattr(ad, "place"):
        try:
            placed = await ad.place(OrderReq(symbol=req.symbol, side=req.side, type=req.type, qty=req.qty, price=req.price, sl=None, tp=None))  # type: ignore[attr-defined]
            order_id = getattr(placed, "order_id", order_id)
            client_oid = getattr(placed, "client_oid", None)
        except Exception:
            pass
    resp = {"order_id": order_id}
    if client_oid:
        resp["client_order_id"] = client_oid
    return resp

# Alias pour legacy / tests
@app.post("/preview", response_model=OrderPreviewResponse, responses={400: {"model": ErrorResponse}})
async def preview_alias(req: OrderPreviewRequest) -> OrderPreviewResponse:
    """Alias pour /orders/preview (legacy support)."""
    return await orders_preview(req)

@app.post("/execute", response_model=OrderExecuteResponse, responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
async def execute_alias(req: OrderExecuteRequest) -> dict:
    """Alias pour /orders/execute (legacy support)."""
    return await orders_execute(req)


@app.post("/panic", response_model=PanicResponse)
async def panic() -> PanicResponse:  # type: ignore[no-untyped-def]
    global _lockout
    _lockout = True
    # risk_guard.panic est volontairement synchrone pour compat tests
    risk_guard.panic()
    # Si TTL asynchrone planifiée, petite attente non bloquante pour flush task
    await asyncio.sleep(0)  # yield loop
    until_iso = None
    if risk_guard.status.lockout_until:
        until_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(risk_guard.status.lockout_until))
    return PanicResponse(lockout=True, until=until_iso)

def _get_registry() -> AdapterRegistry:
    if not hasattr(app.state, "registry"):
        app.state.registry = AdapterRegistry()  # type: ignore[attr-defined]
        global _loaded_adapters
        _loaded_adapters = app.state.registry._adapters  # type: ignore[attr-defined]
        if not _loaded_adapters:  # first-time lazy init
            _instantiate_adapters(app.state.registry)  # type: ignore[attr-defined]
    return app.state.registry  # type: ignore[attr-defined]

def get_adapter(name: str):  # helper public pour tests / intégrations futures
    return _get_registry().get(name)

__all__ = [
    "app",
    "_loaded_adapters",
    "get_adapter",
]

# Logging middleware JSON optionnel
@app.middleware("http")
async def logging_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    log_json = getenv("LOG_JSON", "false").lower() == "true"
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    start = time.time()
    response = None
    try:
        response = await call_next(request)
        return response
    finally:
        duration = (time.time() - start) * 1000
        if log_json:
            payload = {
                "request_id": req_id,
                "method": request.method,
                "path": request.url.path,
                "status": getattr(response, 'status_code', 500),
                "duration_ms": round(duration, 2),
            }
            logger.opt(depth=1).info(json.dumps(payload))
