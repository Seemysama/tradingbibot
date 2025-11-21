from __future__ import annotations
"""Async DB repository using SQLAlchemy 2.0 async engine + simple lockout store."""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select
from state.models import Base, Order, Trade, EquitySnapshot, Position, Journal
import os

# Simple lockout store for panic/risk management
class Repo:
    _lockout = False

    @classmethod
    def set_locked(cls, v: bool) -> None:
        cls._lockout = v

    @classmethod
    def is_locked(cls) -> bool:
        return cls._lockout

DB_URL = os.environ.get("DB_URL", "sqlite+aiosqlite:///:memory:")

engine = create_async_engine(DB_URL, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# Création eager pour tests synchrones simples via TestClient
async def _ensure():  # type: ignore[no-untyped-def]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
import asyncio as _asyncio
_asyncio.get_event_loop().run_until_complete(_ensure())

async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def add_order(order_id: str, symbol: str, side: str, type_: str, qty: float, price: float | None) -> None:
    async with SessionLocal() as s:
        s.add(Order(order_id=order_id, symbol=symbol, side=side, type=type_, qty=qty, price=price))
        await s.commit()

async def list_orders(symbol: str | None = None) -> list[Order]:
    async with SessionLocal() as s:
        stmt = select(Order)
        if symbol:
            stmt = stmt.where(Order.symbol == symbol)
        res = await s.execute(stmt)
        return list(res.scalars())

async def add_position(symbol: str, side: str, qty: float, entry_price: float) -> None:
    async with SessionLocal() as s:
        s.add(Position(symbol=symbol, side=side, qty=qty, entry_price=entry_price))
        await s.commit()

async def list_positions() -> list[Position]:
    async with SessionLocal() as s:
        res = await s.execute(select(Position))
        return list(res.scalars())

async def close_all_positions() -> None:
    async with SessionLocal() as s:
        res = await s.execute(select(Position))
        positions = list(res.scalars())
        for p in positions:
            await s.delete(p)
        await s.commit()

async def journal(event: str, data: str) -> None:
    async with SessionLocal() as s:
        s.add(Journal(event=event, data=data))
        await s.commit()

async def add_trade(order_id: str, symbol: str, qty: float, price: float, pnl: float = 0.0) -> None:
    async with SessionLocal() as s:
        s.add(Trade(order_id=order_id, symbol=symbol, qty=qty, price=price, pnl=pnl))
        await s.commit()

async def snapshot_equity(equity: float) -> None:
    async with SessionLocal() as s:
        s.add(EquitySnapshot(equity=equity))
        await s.commit()
