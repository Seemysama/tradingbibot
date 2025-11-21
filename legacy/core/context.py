"""Application global context (singleton-like objects).

Avoid circular imports by centralizing shared singletons here.
"""
from __future__ import annotations
from core.risk import RiskGuard, RiskConfig, EquityState
import os
from interfaces.exchange import MarketRules  # single source of truth

risk_guard = RiskGuard(
    cfg=RiskConfig(
        risk_per_trade=float(os.environ.get("RISK_PER_TRADE", "0.01")),
        daily_dd_max=float(os.environ.get("DAILY_DD_MAX", "0.05")),
        max_leverage=int(os.environ.get("MAX_LEVERAGE", "5")),
        max_concurrent=int(os.environ.get("MAX_CONCURRENT_POS", "5")),
    max_seq_losses=int(os.environ.get("MAX_SEQ_LOSSES", "3")),
    lockout_ttl_seconds=int(os.environ.get("LOCKOUT_TTL_SECONDS", "0")) or None,
    ),
    equity=EquityState(
        starting_equity=10_000.0,
        current_equity=10_000.0,
        daily_high=10_000.0,
        daily_low=10_000.0,
        last_update=0.0,
    ),
)
