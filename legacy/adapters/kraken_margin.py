from __future__ import annotations
"""Kraken Margin skeleton (REAL_ADAPTERS gated)."""
import os, httpx, time
from typing import Dict, Optional
from interfaces.exchange import MarketRules, OrderReq, Preview, Placed
from core.sizing import round_step
from core.symbols import normalize

KRAKEN_API = "https://api.kraken.com"

class KrakenMarginAdapter:  # type: ignore[misc]
	name = "kraken_margin"
	def __init__(self) -> None:
		self.real = os.getenv("REAL_ADAPTERS") == "1"
		self.api_key = os.getenv("KRAKEN_API_KEY", "")
		self.api_secret = os.getenv("KRAKEN_API_SECRET", "")
		self._rules: Dict[str, MarketRules] = {}

	def example_symbol(self) -> str:
		return "XBTUSD"  # Kraken style

	def validate_symbol(self, symbol: str) -> bool:
		"""Validate symbol according to Kraken format (XBT altnames)."""
		norm = normalize("kraken_margin", symbol)
		return norm in {"XBTUSD", "ETHUSD"}

	def _bootstrap(self) -> None:
		if not self.real or self._rules:
			return
		try:
			r = httpx.get(f"{KRAKEN_API}/0/public/AssetPairs", timeout=10)
			r.raise_for_status()
			data = r.json().get("result", {})
			for sym, info in data.items():
				base = info.get("base", "XBT").replace("XBT", "BTC").upper()
				quote = info.get("quote", "USD").replace("ZUSD", "USD").upper()
				symbol = base + quote
				tick = float(info.get("tick_size") or info.get("pair_decimals") or 1)
				step = float(info.get("lot_decimals") or 1e-3)
				self._rules[symbol] = MarketRules(symbol=symbol, base=base, quote=quote, tick_size=tick if tick < 10 else 0.5, step_size=step if step < 1 else 0.001, min_qty=0.0, min_notional=0.0)
		except Exception:
			pass

	def validate_symbol(self, symbol: str) -> bool:
		self._bootstrap()
		sym = symbol.replace("/", "").upper()
		return sym in self._rules or sym in ("BTCUSD", "XBTUSD")

	def get_rules(self, symbol: str) -> Optional[MarketRules]:
		self._bootstrap()
		sym = symbol.replace("/", "").upper().replace("XBT", "BTC")
		return self._rules.get(sym)

	async def preview(self, req: OrderReq) -> Preview:
		rules = self.get_rules(req.symbol) or MarketRules(symbol=req.symbol.replace("/", "").upper(), base="BTC", quote="USD", tick_size=1, step_size=0.001, min_qty=0.0001, min_notional=1)
		qty = req.qty if req.qty is not None else 0.01
		qty = round_step(qty, rules.step_size)
		if qty * (req.price or req.tp or 0) < rules.min_notional:
			qty = 0.0
		return Preview(symbol=rules.symbol, side=req.side, qty=qty, est_max_loss=0, rr=0, sl=req.sl or 0, tp=req.tp or 0)

	async def place(self, req: OrderReq) -> Placed:
		return Placed(order_id=f"SIM-KR-{int(time.time()*1000)}")

	async def list_markets(self) -> list[MarketRules]:
		"""Méthode requise par le méga-prompt pour lister les marchés."""
		self._bootstrap()
		return list(self._rules.values())

	async def execute(self, req: OrderReq) -> Placed:
		"""Alias pour place() requis par le méga-prompt."""
		return await self.place(req)

	async def connect(self) -> None: return None
	async def fetch_markets(self) -> list[MarketRules]: self._bootstrap(); return list(self._rules.values())
	async def cancel_all(self, symbol: Optional[str] = None) -> None: return None
	async def positions(self) -> list[dict]: return []

Adapter = KrakenMarginAdapter
