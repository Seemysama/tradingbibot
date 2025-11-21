from __future__ import annotations
"""Coinbase Advanced skeleton (REAL_ADAPTERS gated).

Réseau uniquement si REAL_ADAPTERS=1, sinon réponses mock.
"""
import os, httpx, time
from typing import Dict, Optional
from interfaces.exchange import MarketRules, OrderReq, Preview, Placed
from core.sizing import round_step
from core.symbols import normalize

COINBASE_API = "https://api.coinbase.com"

class CoinbaseAdvancedAdapter:  # type: ignore[misc]
	name = "coinbase_advanced"
	def __init__(self) -> None:
		self.real = os.getenv("REAL_ADAPTERS") == "1"
		self.api_key = os.getenv("COINBASE_API_KEY", "")
		self.api_secret = os.getenv("COINBASE_API_SECRET", "")
		self._rules: Dict[str, MarketRules] = {}

	def example_symbol(self) -> str:
		return "BTC-USD"

	def validate_symbol(self, symbol: str) -> bool:
		"""Validate symbol according to Coinbase format (with dashes)."""
		norm = normalize("coinbase_advanced", symbol)
		return "-" in norm

	def _bootstrap(self) -> None:
		if not self.real or self._rules:
			return
		try:
			r = httpx.get(f"{COINBASE_API}/api/v3/brokerage/products", timeout=10)
			r.raise_for_status()
			data = r.json()
			for p in data.get("products", []):
				if p.get("status") != "online":
					continue
				base = p.get("base_currency", "BTC").upper()
				quote = p.get("quote_currency", "USD").upper()
				symbol = base + quote
				tick = float(p.get("quote_increment") or 0.01)
				step = float(p.get("base_increment") or 0.0001)
				min_qty = float(p.get("base_min_size") or 0)
				min_notional = float(p.get("min_market_funds") or 0)
				self._rules[symbol] = MarketRules(symbol=symbol, base=base, quote=quote, tick_size=tick, step_size=step, min_qty=min_qty, min_notional=min_notional)
		except Exception:
			pass

	def validate_symbol(self, symbol: str) -> bool:
		self._bootstrap()
		sym = symbol.replace("-", "").upper()
		return sym in self._rules or sym == "BTCUSD"

	def get_rules(self, symbol: str) -> Optional[MarketRules]:
		self._bootstrap()
		return self._rules.get(symbol.replace("-", "").upper())

	async def preview(self, req: OrderReq) -> Preview:
		rules = self.get_rules(req.symbol) or MarketRules(symbol=req.symbol.replace("-", "").upper(), base="BTC", quote="USD", tick_size=0.01, step_size=0.0001, min_qty=0.0001, min_notional=1)
		qty = req.qty if req.qty is not None else 0.01
		qty = round_step(qty, rules.step_size)
		if qty * (req.price or req.tp or 0) < rules.min_notional:
			qty = 0.0
		return Preview(symbol=rules.symbol, side=req.side, qty=qty, est_max_loss=0, rr=0, sl=req.sl or 0, tp=req.tp or 0)

	async def place(self, req: OrderReq) -> Placed:
		return Placed(order_id=f"SIM-CB-{int(time.time()*1000)}")

	async def list_markets(self) -> list[MarketRules]:
		"""Méthode requise par le méga-prompt pour lister les marchés."""
		self._bootstrap()
		return list(self._rules.values())

	async def execute(self, req: OrderReq) -> Placed:
		"""Alias pour place() requis par le méga-prompt."""
		return await self.place(req)

	async def connect(self) -> None: return None
	async def fetch_markets(self) -> list[MarketRules]:
		self._bootstrap(); return list(self._rules.values())
	async def cancel_all(self, symbol: Optional[str] = None) -> None: return None
	async def positions(self) -> list[dict]: return []

Adapter = CoinbaseAdvancedAdapter
