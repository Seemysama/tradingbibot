import logging

logger = logging.getLogger("RiskManager")

class PositionSizer:
    """
    Module de gestion de la taille des positions (Money Management).
    Applique les règles de risque par trade et d'exposition globale.
    """

    @staticmethod
    def calculate_position_size(
        account_balance: float,
        entry_price: float,
        stop_loss: float,
        risk_per_trade_pct: float = 0.01,  # 1% de risque par trade
        max_position_size_pct: float = 0.20 # Max 20% du capital par position
    ) -> float:
        """
        Calcule la quantité à acheter/vendre en respectant :
        1. Le risque max (perte si SL touché).
        2. La taille max de position (exposition notionnelle).
        """
        if entry_price <= 0 or stop_loss <= 0:
            return 0.0

        # 1. Calcul basé sur le risque (Distance au Stop Loss)
        # Risque en $ = Capital * %Risque
        risk_amount = account_balance * risk_per_trade_pct
        # Distance au SL par unité
        sl_distance = abs(entry_price - stop_loss)
        
        if sl_distance == 0:
            qty_risk = 0.0
        else:
            qty_risk = risk_amount / sl_distance

        # 2. Calcul basé sur le capital (Exposition Max)
        # Montant Max Investi = Capital * %MaxPos
        max_invest_amount = account_balance * max_position_size_pct
        qty_capital = max_invest_amount / entry_price

        # 3. On prend le plus petit des deux (Approche conservatrice)
        final_qty = min(qty_risk, qty_capital)

        logger.info(
            f"⚖️ Sizing: Balance={account_balance:.2f}$ | "
            f"RiskQty={qty_risk:.4f} (SL Dist={sl_distance:.2f}$) | "
            f"CapQty={qty_capital:.4f} (MaxExp={max_invest_amount:.2f}$) -> "
            f"Final={final_qty:.4f}"
        )

        return final_qty
