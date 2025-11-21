import logging
import asyncio
from dataclasses import dataclass, field
from typing import Dict, Optional
from src.models import Signal

logger = logging.getLogger("Execution")

@dataclass
class Position:
    symbol: str
    side: str  # "LONG" ou "SHORT"
    entry_price: float
    qty: float
    timestamp: int

@dataclass
class Portfolio:
    balance: float = 10000.0  # Solde en USDT
    positions: Dict[str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0

class ExecutionEngine:
    """
    Moteur d'exécution hybride (Paper Trading / Live).
    Gère le portefeuille, les positions et simule les frais.
    """

    def __init__(self, mode: str = "PAPER", initial_balance: float = 10000.0):
        self.mode = mode
        self.portfolio = Portfolio(balance=initial_balance)
        self.fee_rate = 0.0004  # 0.04% taker fee (Binance Futures standard)
        self.trade_size_usdt = 2000.0 # Taille fixe par trade pour la simulation

    async def execute(self, signal: Signal):
        """Point d'entrée pour exécuter un signal."""
        if self.mode == "PAPER":
            await self._execute_paper(signal)
        else:
            logger.warning("⚠️ Mode LIVE non implémenté. Passage en simulation.")
            await self._execute_paper(signal)

    async def _execute_paper(self, signal: Signal):
        symbol = signal.symbol
        price = signal.price
        
        current_pos = self.portfolio.positions.get(symbol)
        
        # Logique de base : 
        # BUY -> Ouvrir LONG ou Fermer SHORT
        # SELL -> Ouvrir SHORT ou Fermer LONG
        
        if signal.side == "BUY":
            if current_pos:
                if current_pos.side == "SHORT":
                    await self._close_position(symbol, price)
                    # On pourrait flip ici (ouvrir LONG), mais restons simple : Close only
                else:
                    logger.debug(f"⚠️ Ignoré BUY {symbol}: Déjà LONG")
            else:
                await self._open_position(symbol, "LONG", price)

        elif signal.side == "SELL":
            if current_pos:
                if current_pos.side == "LONG":
                    await self._close_position(symbol, price)
                else:
                    logger.debug(f"⚠️ Ignoré SELL {symbol}: Déjà SHORT")
            else:
                await self._open_position(symbol, "SHORT", price)

    async def _open_position(self, symbol: str, side: str, price: float):
        if self.portfolio.balance < self.trade_size_usdt:
            logger.warning(f"❌ Fonds insuffisants pour {side} {symbol}")
            return

        # Calcul quantité (USDT / Prix)
        qty = self.trade_size_usdt / price
        
        # Frais d'entrée
        fee = self.trade_size_usdt * self.fee_rate
        self.portfolio.balance -= fee
        
        pos = Position(
            symbol=symbol,
            side=side,
            entry_price=price,
            qty=qty,
            timestamp=int(asyncio.get_running_loop().time())
        )
        self.portfolio.positions[symbol] = pos
        
        logger.info(
            f"🔵 OPEN {side} {symbol} @ {price:.2f}$ | "
            f"Qty: {qty:.4f} | Fee: {fee:.2f}$ | "
            f"Solde: {self.portfolio.balance:.2f}$"
        )

    async def _close_position(self, symbol: str, price: float):
        pos = self.portfolio.positions.pop(symbol)
        
        # Valeur de sortie
        exit_value = pos.qty * price
        
        # Frais de sortie
        fee = exit_value * self.fee_rate
        
        # Calcul PnL
        if pos.side == "LONG":
            raw_pnl = (price - pos.entry_price) * pos.qty
        else: # SHORT
            raw_pnl = (pos.entry_price - price) * pos.qty
            
        net_pnl = raw_pnl - fee
        
        # Mise à jour portefeuille (On rend la mise initiale + PnL)
        # Note: Dans ce modèle simplifié, 'balance' est le cash disponible.
        # A l'ouverture on n'a pas déduit le collatéral (juste les frais), 
        # donc on ajoute juste le PnL net au solde.
        self.portfolio.balance += net_pnl
        self.portfolio.realized_pnl += net_pnl
        
        icon = "🟢" if net_pnl > 0 else "🔴"
        logger.info(
            f"{icon} CLOSE {pos.side} {symbol} @ {price:.2f}$ | "
            f"PnL: {net_pnl:+.2f}$ | "
            f"Solde: {self.portfolio.balance:.2f}$"
        )
