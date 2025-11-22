import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Literal, Optional

from src.risk_management import PositionSizer
from src.models import Signal

try:
    # Préférence : payload structuré
    from src.utils import broadcast_event as broadcast_json
except Exception:  # pragma: no cover - fallback défensif
    async def broadcast_json(event_type: str, data: dict):
        pass


logger = logging.getLogger("ExecutionEngine")


@dataclass
class Position:
    symbol: str
    side: Literal["LONG", "SHORT"]
    entry_price: float
    qty: float
    timestamp: float
    stop_loss: float = 0.0
    take_profit: float = 0.0


@dataclass
class Portfolio:
    balance: float = 10_000.0
    positions: Dict[str, Position] = field(default_factory=dict)


class ExecutionEngine:
    """
    Moteur d'exécution PAPER.
    - Gère le cash (balance) et les positions.
    - Calcule PnL réalisé/latent.
    - Broadcast en temps réel les trades et le PnL.
    """

    def __init__(self, initial_balance: float = 10_000.0, max_position_pct: float = 0.20, cooldown_ms: int = 3000):
        self.initial_balance = initial_balance
        self.max_position_pct = max_position_pct
        self.cooldown_ms = cooldown_ms
        self._last_exec_ts: Dict[str, float] = {}
        self._marks: Dict[str, float] = {}
        self.state_path = Path("data") / "portfolio_state.json"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.portfolio = Portfolio(balance=initial_balance)
        self._load_state()

    # -------------------- API publique -------------------- #
    async def on_signal(self, signal: Signal):
        """Point d'entrée unique pour appliquer un signal."""
        price = signal.price
        symbol = signal.symbol
        side = signal.side

        # Cooldown anti-whipsaw
        if not self.check_cooldown(symbol, signal.timestamp):
            return

        # Vérification notional minimal
        if not self.check_min_notional(price, 0.001):  # quantité minimale testée après sizing
            return

        # Sizing conservateur (1% risque, 20% max exposition)
        qty = PositionSizer.calculate_position_size(
            account_balance=self.portfolio.balance,
            entry_price=price,
            stop_loss=signal.stop_loss if signal.stop_loss > 0 else price * 0.98,
            risk_per_trade_pct=0.01,
            max_position_size_pct=self.max_position_pct,
        )
        if qty <= 0 or not self.check_min_notional(price, qty):
            logger.warning(f"⛔ Signal rejeté (sizing nul ou notional insuffisant) {symbol}")
            return

        # Si position existante
        current = self.portfolio.positions.get(symbol)
        if current:
            if (current.side == "LONG" and side == "SELL") or (current.side == "SHORT" and side == "BUY"):
                await self._close_position(symbol, price)
            elif current.side == "LONG" and side == "BUY":
                logger.info(f"🛡️ Déjà LONG {symbol}, signal ignoré.")
                return
            elif current.side == "SHORT" and side == "SELL":
                logger.info(f"🛡️ Déjà SHORT {symbol}, signal ignoré.")
                return

        await self._open_position(symbol, side, price, qty, signal)
        self._last_exec_ts[symbol] = signal.timestamp
        await self.broadcast_portfolio(price_hint={symbol: price})

    def update_mark(self, symbol: str, price: float):
        """Met à jour le prix de référence pour le mark-to-market."""
        self._marks[symbol] = price

    # -------------------- Persistance -------------------- #
    def _load_state(self):
        if not self.state_path.exists():
            return
        try:
            with self.state_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            balance = float(data.get("balance", self.initial_balance))
            positions_raw = data.get("positions", {})
            positions: Dict[str, Position] = {}
            for sym, p in positions_raw.items():
                try:
                    positions[sym] = Position(
                        symbol=sym,
                        side=p["side"],
                        entry_price=float(p["entry_price"]),
                        qty=float(p["qty"]),
                        timestamp=float(p.get("timestamp", time.time())),
                        stop_loss=float(p.get("stop_loss", 0.0)),
                        take_profit=float(p.get("take_profit", 0.0)),
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Position corrompue ignorée ({sym}): {e}")
            self.portfolio = Portfolio(balance=balance, positions=positions)
            logger.info(f"♻️ État restauré : Balance={balance:.2f}, Positions={len(positions)}")
        except Exception as e:
            logger.warning(f"⚠️ Impossible de charger l'état du portefeuille: {e}")

    def _save_state(self):
        try:
            payload = {
                "balance": self.portfolio.balance,
                "positions": {
                    sym: {
                        "side": pos.side,
                        "entry_price": pos.entry_price,
                        "qty": pos.qty,
                        "timestamp": pos.timestamp,
                        "stop_loss": pos.stop_loss,
                        "take_profit": pos.take_profit,
                    }
                    for sym, pos in self.portfolio.positions.items()
                },
            }
            tmp_path = self.state_path.with_suffix(".json.tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp_path, self.state_path)
        except Exception as e:
            logger.warning(f"⚠️ Sauvegarde d'état échouée: {e}")

    # -------------------- Internes -------------------- #
    def check_min_notional(self, price: float, qty: float) -> bool:
        return price * qty >= 5.0

    def check_cooldown(self, symbol: str, ts_ms: int) -> bool:
        last = self._last_exec_ts.get(symbol)
        if last and ts_ms - last < self.cooldown_ms:
            logger.warning(f"⏳ Cooldown actif pour {symbol} ({self.cooldown_ms}ms)")
            return False
        return True

    async def _open_position(self, symbol: str, side: Literal["BUY", "SELL"], price: float, qty: float, signal: Signal):
        pos_side: Literal["LONG", "SHORT"] = "LONG" if side == "BUY" else "SHORT"

        cost = price * qty
        if cost > self.portfolio.balance:
            logger.warning(f"❌ Fonds insuffisants pour {symbol} (requis {cost:.2f}$, dispo {self.portfolio.balance:.2f}$)")
            return

        self.portfolio.balance -= cost
        self.portfolio.positions[symbol] = Position(
            symbol=symbol,
            side=pos_side,
            entry_price=price,
            qty=qty,
            timestamp=time.time(),
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
        )

        await broadcast_json("trade", {"type": "trade", "symbol": symbol, "side": side, "price": price, "qty": qty})
        logger.info(f"💰 OUVERTURE {pos_side} {symbol} Qty={qty} @ {price}")
        self._save_state()

    async def _close_position(self, symbol: str, price: float):
        pos = self.portfolio.positions.pop(symbol)
        qty = pos.qty
        # PnL strict : LONG = (exit - entry) * qty, SHORT = (entry - exit) * qty
        pnl = (price - pos.entry_price) * qty if pos.side == "LONG" else (pos.entry_price - price) * qty

        # Restitution du cash et PnL
        self.portfolio.balance += pos.entry_price * qty + pnl

        await broadcast_json("trade", {"type": "trade", "symbol": symbol, "side": f"CLOSE_{pos.side}", "price": price, "qty": qty, "pnl": pnl})
        logger.info(f"🔔 FERMETURE {pos.side} {symbol} Qty={qty} @ {price} | PnL={pnl:.2f}")
        self._save_state()

    def _compute_equity(self, price_hint: Optional[Dict[str, float]] = None):
        price_hint = price_hint or {}
        equity = self.portfolio.balance
        total_unrealized = 0.0
        positions_view = []

        for sym, pos in self.portfolio.positions.items():
            mark = price_hint.get(sym) or self._marks.get(sym) or pos.entry_price
            # PnL strict : LONG = (mark - entry) * qty, SHORT = (entry - mark) * qty
            unrealized = (mark - pos.entry_price) * pos.qty if pos.side == "LONG" else (pos.entry_price - mark) * pos.qty
            total_unrealized += unrealized

            positions_view.append(
                {
                    "symbol": sym,
                    "side": pos.side,
                    "entry": pos.entry_price,
                    "mark": mark,
                    "qty": pos.qty,
                    "pnl": unrealized,
                }
            )

        equity += total_unrealized
        return equity, total_unrealized, positions_view

    async def broadcast_portfolio(self, price_hint: Optional[Dict[str, float]] = None):
        equity, unrealized, positions_view = self._compute_equity(price_hint)
        payload = {
            "type": "pnl",
            "balance": self.portfolio.balance,
            "equity": equity,
            "pnl_unrealized": unrealized,
            "positions": positions_view,
            "timestamp": time.time(),
        }
        await broadcast_json("pnl", payload)
