from __future__ import annotations
"""RiskGuard implementation.

Features:
- Per trade max risk (percentage of equity)
- Daily drawdown limit & lockout
- Sequential loss lockout
- Max concurrent positions
- Panic lockout & close request flag
"""
from dataclasses import dataclass, field
from typing import Optional
import time, asyncio

__all__ = [
    "EquityState",
    "RiskConfig",
    "RiskStatus",
    "RiskGuard",
]

@dataclass
class EquityState:
    starting_equity: float
    current_equity: float
    daily_high: float
    daily_low: float
    last_update: float

@dataclass
class RiskConfig:
    risk_per_trade: float = 0.01  # 1%
    daily_dd_max: float = 0.05    # 5%
    max_leverage: int = 5
    max_concurrent: int = 5
    max_seq_losses: int = 3
    lockout_ttl_seconds: int | None = None  # durée max du lockout panic avant auto-unlock

@dataclass
class RiskStatus:
    lockout: bool = False
    seq_losses: int = 0
    trades_today: int = 0
    panic: bool = False
    lockout_until: float | None = None  # epoch seconds

@dataclass
class RiskGuard:
    cfg: RiskConfig
    equity: EquityState
    status: RiskStatus = field(default_factory=RiskStatus)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def _daily_dd(self) -> float:
        dd = (self.equity.starting_equity - self.equity.current_equity) / self.equity.starting_equity
        return max(0.0, dd)

    def _refresh_timeouts(self) -> None:
        if self.status.lockout_until and time.time() >= self.status.lockout_until:
            # TTL expirée => unlock si panic uniquement (sécurité simple)
            self.status.lockout = False
            self.status.panic = False
            self.status.lockout_until = None

    def check_lockout(self) -> None:
        self._refresh_timeouts()
        if self._daily_dd() >= self.cfg.daily_dd_max:
            self.status.lockout = True
        if self.status.seq_losses >= self.cfg.max_seq_losses:
            self.status.lockout = True
        if self.status.panic:
            self.status.lockout = True

    def is_locked(self) -> bool:
        self.check_lockout()
        return self.status.lockout

    def can_trade(self, open_positions: int | None = None) -> bool:
        if self.is_locked():
            return False
        if open_positions is not None and open_positions >= self.cfg.max_concurrent:
            return False
        return True

    def record_trade_result(self, pnl: float) -> None:
        self.status.trades_today += 1
        if pnl < 0:
            self.status.seq_losses += 1
        else:
            self.status.seq_losses = 0
        self.equity.current_equity += pnl
        self.equity.daily_high = max(self.equity.daily_high, self.equity.current_equity)
        self.equity.daily_low = min(self.equity.daily_low, self.equity.current_equity)
        self.check_lockout()

    def max_risk_amount(self) -> float:
        return self.equity.current_equity * self.cfg.risk_per_trade

    async def _panic_async(self) -> None:
        """Internal async panic implementation (idempotent)."""
        async with self._lock:
            self.status.panic = True
            self.status.lockout = True
            if self.cfg.lockout_ttl_seconds:
                self.status.lockout_until = time.time() + self.cfg.lockout_ttl_seconds

    def panic(self) -> None:
        """Public synchronous panic interface expected by existing tests.

        If called inside a running event loop, schedule the async implementation
        without blocking; otherwise run inline synchronously. If lock already
        held, set flags directly (best‑effort) to avoid deadlock.
        """
        if self._lock.locked():  # fast path – already in panic or resetting
            self.status.panic = True
            self.status.lockout = True
            if self.cfg.lockout_ttl_seconds and not self.status.lockout_until:
                self.status.lockout_until = time.time() + self.cfg.lockout_ttl_seconds
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._panic_async())
        except RuntimeError:
            # No running loop: execute synchronously
            # (Create a temporary loop to honor TTL logic atomically)
            try:
                asyncio.run(self._panic_async())
            except RuntimeError:
                # Fallback last resort (e.g. nested event loop constraints)
                self.status.panic = True
                self.status.lockout = True
                if self.cfg.lockout_ttl_seconds and not self.status.lockout_until:
                    self.status.lockout_until = time.time() + self.cfg.lockout_ttl_seconds

    async def reset_daily(self) -> None:
        async with self._lock:
            now = time.time()
            self.equity.starting_equity = self.equity.current_equity
            self.equity.daily_high = self.equity.current_equity
            self.equity.daily_low = self.equity.current_equity
            self.equity.last_update = now
            self.status.trades_today = 0
            self.status.seq_losses = 0
            if not self.status.panic:
                self.status.lockout = False
            self._refresh_timeouts()
