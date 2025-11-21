from __future__ import annotations
"""Binance Spot adapter skeleton (REAL_ADAPTERS gated).

Par défaut (REAL_ADAPTERS != 1) : opérations mock sans réseau.
"""
import os, httpx, time
from typing import Any, Optional, Dict
from interfaces.exchange import MarketRules, OrderReq, Preview, Placed
from core.symbols import normalize
from core.sizing import round_step
from core.ratelimit import RateLimiter

BINANCE_API = "https://api.binance.com"

class BinanceSpotAdapter:  # type: ignore[misc]
	name = "binance_spot"
	def __init__(self) -> None:
		self.real = os.getenv("REAL_ADAPTERS") == "1"
		self.api_key = os.getenv("BINANCE_API_KEY", "")
		self.api_secret = os.getenv("BINANCE_API_SECRET", "")
		self._rules: Dict[str, MarketRules] = {}
		self._rl_boot = RateLimiter(capacity=2, refill_rate=0.2)  # max 2 bootstrap appels rapprochés
		self._rl_order = RateLimiter(capacity=5, refill_rate=1)   # 5 requêtes place / sec (sim)

	def example_symbol(self) -> str:
		return "BTCUSDT"

	def validate_symbol(self, symbol: str) -> bool:
		"""Validate symbol according to Binance format (no dashes)."""
		from core.symbols import normalize
		norm = normalize("binance_spot", symbol)
		if "-" in symbol:  # Binance rejects dashes
			return False
		return norm.endswith("USDT") or norm.endswith("BTC")

	def _bootstrap(self) -> None:
		if not self.real or self._rules:
			return
		if not self._rl_boot.allow():  # évite spam sous forte contention
			return
		try:
			r = httpx.get(f"{BINANCE_API}/api/v3/exchangeInfo", timeout=10)
			r.raise_for_status()
			data = r.json()
			for s in data.get("symbols", []):
				if s.get("status") != "TRADING":
					continue
				sym = s["symbol"].upper()
				base, quote = s["baseAsset"].upper(), s["quoteAsset"].upper()
				tick = step = min_qty = min_notional = 0.0
				for f in s.get("filters", []):
					t = f.get("filterType")
					if t == "PRICE_FILTER":
						tick = float(f.get("tickSize", 0) or 0)
					elif t == "LOT_SIZE":
						step = float(f.get("stepSize", 0) or 0)
						min_qty = float(f.get("minQty", 0) or 0)
					elif t == "MIN_NOTIONAL":
						min_notional = float(f.get("minNotional", 0) or 0)
				self._rules[sym] = MarketRules(symbol=sym, base=base, quote=quote, tick_size=tick or 0.01, step_size=step or 0.001, min_qty=min_qty or 0.0, min_notional=min_notional or 0.0)
		except Exception:
			# Silent fallback to mock
			pass

	def validate_symbol(self, symbol: str) -> bool:
		self._bootstrap()
		n = normalize("binance_spot", symbol)
		return n in self._rules or n == "BTCUSDT"  # minimal fallback

	def get_rules(self, symbol: str) -> Optional[MarketRules]:
		self._bootstrap()
		return self._rules.get(normalize("binance_spot", symbol))

	async def preview(self, req: OrderReq) -> Preview:
		rules = self.get_rules(req.symbol) or MarketRules(symbol=normalize("binance_spot", req.symbol), base="BTC", quote="USDT", tick_size=0.1, step_size=0.001, min_qty=0.001, min_notional=5)
		qty = req.qty if req.qty is not None else 0.01
		qty = round_step(qty, rules.step_size)
		if qty * (req.price or req.tp or 0) < rules.min_notional:
			qty = 0.0
		return Preview(symbol=rules.symbol, side=req.side, qty=qty, est_max_loss=0, rr=0, sl=req.sl or 0, tp=req.tp or 0)

	async def place(self, req: OrderReq) -> Placed:
		# Rate limit simulation
		if not self._rl_order.allow():
			return Placed(order_id="RATE-LIMIT")
		return Placed(order_id=f"SIM-BIN-{int(time.time()*1000)}")

	async def list_markets(self) -> list[MarketRules]:
		"""Méthode requise par le méga-prompt pour lister les marchés."""
		self._bootstrap()
		return list(self._rules.values())

	async def execute(self, req: OrderReq) -> Placed:
		"""Alias pour place() requis par le méga-prompt."""
		return await self.place(req)

	async def connect(self) -> None:  # compatibility
		return None
	async def fetch_markets(self) -> list[MarketRules]:  # compatibility
		self._bootstrap()
		return list(self._rules.values())
	async def cancel_all(self, symbol: Optional[str] = None) -> None:
		return None
	async def positions(self) -> list[dict]:
		return []

Adapter = BinanceSpotAdapter
