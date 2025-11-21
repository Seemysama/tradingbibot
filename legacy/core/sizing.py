from __future__ import annotations
"""Position sizing respecting exchange market rules."""
from math import floor
from interfaces.exchange import MarketRules

__all__ = [
    "round_step",
    "round_price",
    "normalize_order",
    "meets_min_qty",
    "meets_min_notional",
    "size_from_risk",
    "enforce_min_notional",
    "round_qty_strict",
]

def round_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    n = int(value / step + 1e-12)
    return n * step

def round_price(price: float, tick: float) -> float:
    if tick <= 0:
        return price
    return round_step(price, tick)

def round_tick(price: float, tick: float) -> float:  # alias explicite demandé
    return round_price(price, tick)

def normalize_order(price: float | None, qty: float, rules: MarketRules) -> tuple[float | None, float]:
    if price is not None:
        price = round_price(price, rules.tick_size)
    qty = round_step(qty, rules.step_size)
    return price, qty

def meets_min_qty(qty: float, rules: MarketRules) -> bool:
    return qty >= rules.min_qty

def meets_min_notional(qty: float, entry: float, rules: MarketRules) -> bool:
    if entry <= 0:
        return False
    return qty * entry >= rules.min_notional

def size_from_risk(risk_amount: float, entry: float, stop: float, rules: MarketRules) -> float:
    """Calcule la taille de position basée sur un montant de risque."""
    if entry <= 0 or stop <= 0 or entry == stop:
        return 0.0
    
    # Si le risk_amount est inférieur au min_notional, retourner 0
    if risk_amount < rules.min_notional:
        return 0.0
    
    raw = abs(risk_amount / abs(entry - stop))
    stepped = (raw // rules.step_size) * rules.step_size
    notional = stepped * entry
    if stepped < rules.min_qty or notional < rules.min_notional:
        return 0.0
    return round(stepped, 8)

def enforce_min_notional(qty: float, entry_price: float, rules: MarketRules) -> float:
    """Garde-fou strict: applique min_notional et rejette si impossible."""
    if entry_price <= 0:
        return 0.0
    # Vérifie d'abord si la qty proposée respecte min_notional
    if meets_min_notional(qty, entry_price, rules):
        return qty
    # Calcule la qty minimale pour respecter min_notional
    min_qty_for_notional = rules.min_notional / entry_price
    # Arrondi au step supérieur si nécessaire
    adjusted_qty = round_step(min_qty_for_notional, rules.step_size)
    if adjusted_qty < min_qty_for_notional:
        # Round up to next step
        adjusted_qty += rules.step_size
    # Vérifie que ça respecte maintenant min_notional et min_qty
    if adjusted_qty >= rules.min_qty and meets_min_notional(adjusted_qty, entry_price, rules):
        return adjusted_qty
    return 0.0  # Impossible de respecter les contraintes

def round_qty_strict(qty: float, rules: MarketRules) -> float:
    """Arrondi strict avec step_size, applique min_qty."""
    rounded = round_step(qty, rules.step_size)
    return rounded if rounded >= rules.min_qty else 0.0
