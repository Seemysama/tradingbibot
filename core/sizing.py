import logging

logger = logging.getLogger("RiskManager")


class PositionSizer:
    """
    Calcule la taille de position avec la règle du Moindre des deux :
    - Risque max : perte au stop <= risk_per_trade_pct * capital.
    - Exposition max : notionnel <= max_position_size_pct * capital.
    """

    @staticmethod
    def calculate_position_size(
        account_balance: float,
        entry_price: float,
        stop_loss: float,
        risk_per_trade_pct: float = 0.01,
        max_position_size_pct: float = 0.20,
    ) -> float:
        if entry_price <= 0 or stop_loss <= 0 or account_balance <= 0:
            return 0.0

        risk_amount = account_balance * risk_per_trade_pct
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance == 0:
            return 0.0

        qty_risk = risk_amount / sl_distance
        max_notional = account_balance * max_position_size_pct
        qty_cap = max_notional / entry_price

        final_qty = min(qty_risk, qty_cap)

        logger.info(
            f"⚖️ Sizing: balance={account_balance:.2f} risk_qty={qty_risk:.4f} "
            f"cap_qty={qty_cap:.4f} -> final={final_qty:.4f}"
        )
        return final_qty
