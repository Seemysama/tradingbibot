import logging
import asyncio
import math
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict
from src.models import Signal
from core.sizing import PositionSizer

# Import conditionnel pour éviter de casser les tests si core.logger manque
try:
    from core.logger import broadcast_log
except ImportError:
    async def broadcast_log(msg): pass

logger = logging.getLogger("Execution")

@dataclass
class Position:
    symbol: str
    side: str  # "LONG" ou "SHORT"
    entry_price: float
    qty: float
    timestamp: int
    stop_loss: float = 0.0
    take_profit: float = 0.0

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

    def __init__(self, mode: str = "PAPER", initial_balance: float = 10000.0, max_position_pct: float = 0.2):
        self.mode = mode
        self.initial_balance = initial_balance # Pour calcul du % de performance
        self.portfolio = Portfolio(balance=initial_balance)
        self.fee_rate = 0.0004  # 0.04% taker fee (Binance Futures standard)
        self.max_position_pct = max_position_pct
        
        # Safety Checks State
        self.max_processed_signals = 1000
        self.processed_signals: OrderedDict[str, None] = OrderedDict()
        self.last_closure_time: Dict[str, float] = {} # {symbol: timestamp}

    async def execute(self, signal: Signal):
        """Alias pour on_signal (compatibilité main.py)."""
        await self.on_signal(signal)

    async def on_signal(self, signal: Signal):
        """Point d'entrée pour exécuter un signal."""
        # 1. Check Idempotency
        if not self.check_idempotency(signal.id):
            return

        # Log et Broadcast du Signal
        log_msg = f"🔔 SIGNAL REÇU: {signal.symbol} {signal.side} @ {signal.price}"
        logger.info(log_msg)
        await broadcast_log(log_msg)

        if self.mode == "PAPER":
            await self._execute_paper(signal)
            
            # Broadcast du PnL mis à jour après exécution
            # On utilise le prix du signal comme prix courant pour l'estimation
            current_equity = self.get_equity(signal.price)
            pnl_total = current_equity - self.initial_balance
            await broadcast_log(f"PnL: {pnl_total:.2f}")
            
        else:
            logger.warning("⚠️ Mode LIVE non implémenté. Passage en simulation.")
            await self._execute_paper(signal)

    # --- Safety Checks ---

    def check_min_notional(self, price: float, qty: float) -> bool:
        """Vérifie si la valeur de l'ordre respecte le minimum requis (ex: 5$ sur Binance)."""
        notional = price * qty
        if notional < 5.0:
            logger.warning(f"⛔ ORDER REJECTED: Min Notional ({notional:.2f}$ < 5.0$)")
            return False
        return True

    def normalize_quantity(self, qty: float, step_size: float = 0.001) -> float:
        """Arrondit la quantité à la précision du marché pour éviter les erreurs API."""
        precision = int(round(-math.log(step_size, 10), 0))
        return round(qty, precision)

    def check_idempotency(self, signal_id: str) -> bool:
        """Vérifie si le signal a déjà été traité."""
        if signal_id in self.processed_signals:
            logger.warning(f"🛡️ IDEMPOTENCY: Signal {signal_id} déjà traité")
            return False
        self.processed_signals[signal_id] = None
        # On limite la taille pour éviter la dérive mémoire
        if len(self.processed_signals) > self.max_processed_signals:
            self.processed_signals.popitem(last=False)
        return True

    def check_cooldown(self, symbol: str, current_timestamp: int) -> bool:
        """Vérifie le délai depuis la dernière fermeture de position."""
        last_time = self.last_closure_time.get(symbol, 0)
        # Cooldown de 5 secondes (5000 ms)
        if current_timestamp - last_time < 5000:
            logger.warning(f"⏳ COOLDOWN: Trop tôt pour trader {symbol} (Whipsaw protection)")
            return False
        return True

    async def _execute_paper(self, signal: Signal):
        symbol = signal.symbol
        price = signal.price
        timestamp = signal.timestamp
        
        current_pos = self.portfolio.positions.get(symbol)
        
        # Logique : Gestion des positions existantes (Fermeture ou Renversement)
        
        if signal.side == "BUY":
            # Si on est SHORT, on ferme tout d'abord
            if current_pos and current_pos.side == "SHORT":
                await self._close_position(symbol, price)
                self.last_closure_time[symbol] = timestamp
                current_pos = None
            
            # Si on n'est pas déjà LONG, on ouvre
            if not current_pos:
                if not self.check_cooldown(symbol, timestamp):
                    return
                await self._open_position(symbol, "LONG", price, signal.stop_loss, signal.take_profit)

        elif signal.side == "SELL":
            # Si on est LONG, on ferme tout d'abord
            if current_pos and current_pos.side == "LONG":
                await self._close_position(symbol, price)
                self.last_closure_time[symbol] = timestamp
                current_pos = None
            
            # Si on n'est pas déjà SHORT, on ouvre
            if not current_pos:
                if not self.check_cooldown(symbol, timestamp):
                    return
                await self._open_position(symbol, "SHORT", price, signal.stop_loss, signal.take_profit)

    async def _open_position(self, symbol: str, side: str, price: float, sl: float = 0.0, tp: float = 0.0):
        # Utilisation du PositionSizer pour déterminer la quantité
        # On utilise le solde TOTAL (balance + equity) pour le calcul du % de capital, 
        # mais ici on simplifie en utilisant le cash disponible (balance) pour ne pas surexposer.
        # Idéalement : equity = balance + unrealized_pnl
        
        qty = PositionSizer.calculate_position_size(
            account_balance=self.portfolio.balance,
            entry_price=price,
            stop_loss=sl if sl > 0 else price * 0.95, # Fallback SL 5% si non fourni
            risk_per_trade_pct=0.01, # 1% risque
            max_position_size_pct=self.max_position_pct
        )
        
        if qty <= 0:
            logger.warning(f"⚠️ Quantité calculée nulle pour {symbol} (Fonds insuffisants ou SL invalide)")
            return

        # 2. Normalize Quantity
        qty = self.normalize_quantity(qty)

        # 3. Check Min Notional
        if not self.check_min_notional(price, qty):
            return

        # Recalcule le coût après normalisation
        cost = qty * price
        fee = cost * self.fee_rate
        total_debit = cost + fee

        if total_debit > self.portfolio.balance:
            logger.warning(
                f"❌ Fonds insuffisants pour {side} {symbol} "
                f"(Requis: {total_debit:.2f}$, Dispo: {self.portfolio.balance:.2f}$)"
            )
            return
        
        # Mise à jour solde (inclut les frais d'entrée)
        self.portfolio.balance -= total_debit
        
        pos = Position(
            symbol=symbol,
            side=side,
            entry_price=price,
            qty=qty,
            timestamp=int(asyncio.get_running_loop().time()),
            stop_loss=sl,
            take_profit=tp
        )
        self.portfolio.positions[symbol] = pos
        
        logger.info(
            f"💰 TRADE EXECUTÉ | Type: {side} | Prix: {price:.2f}$ | "
            f"Qty: {qty} | Cost: {cost:.2f}$ | Fee: {fee:.2f}$"
        )
        await broadcast_log(f"OPEN {side} {symbol} Qty:{qty} @ {price}$")

    async def _close_position(self, symbol: str, price: float):
        pos = self.portfolio.positions.pop(symbol)
        
        # Valeur brute de sortie
        exit_value = pos.qty * price
        
        # Frais de sortie
        fee = exit_value * self.fee_rate
        
        # Calcul PnL
        if pos.side == "LONG":
            # On récupère la valeur de sortie
            gross_return = exit_value
            pnl = (price - pos.entry_price) * pos.qty
        else: # SHORT
            # Short: On a "emprunté" et vendu au début (crédité cash théorique), on rachète maintenant.
            # Dans notre modèle simplifié cash-based :
            # On récupère le coût initial + PnL
            initial_cost = pos.qty * pos.entry_price
            diff = (pos.entry_price - price) / pos.entry_price
            pnl = initial_cost * diff
            gross_return = initial_cost + pnl

        net_return = gross_return - fee

        # Retour des fonds dans le solde
        self.portfolio.balance += net_return
        self.portfolio.realized_pnl += pnl
        
        self._log_status("CLOSE " + pos.side, price, fee)
        await broadcast_log(f"CLOSE {pos.side} {symbol} PnL:{pnl:.2f}$")

    def _log_status(self, action: str, price: float, fee: float):
        total_equity = self.get_equity(price) # Estimation rapide
        
        perf_pct = ((total_equity - self.initial_balance) / self.initial_balance) * 100
        
        logger.info(
            f"💰 TRADE EXECUTÉ | Type: {action} | Prix: {price:.2f}$ | "
            f"Equity: {total_equity:.2f}$ ({perf_pct:+.2f}%) | Fee: {fee:.2f}$"
        )

    def get_equity(self, current_price: float) -> float:
        """Calcule la valeur totale du portefeuille (Cash + Positions latentes)."""
        equity = self.portfolio.balance
        
        for pos in self.portfolio.positions.values():
            if pos.side == "LONG":
                # Valeur de la position Long
                market_value = pos.qty * current_price
                # On pourrait déduire les frais de sortie théoriques pour être plus précis
                # exit_fee = market_value * self.fee_rate
                # equity += market_value - exit_fee
                equity += market_value
            
            elif pos.side == "SHORT":
                # Valeur de la position Short (Simplifié comme dans _close_position)
                # PnL = Investissement * (Entry - Current) / Entry
                diff = (pos.entry_price - current_price) / pos.entry_price
                initial_invest = pos.qty * pos.entry_price
                pnl = initial_invest * diff
                
                # La valeur récupérable est l'investissement initial + PnL
                recoverable = initial_invest + pnl
                equity += recoverable
                
        return equity
