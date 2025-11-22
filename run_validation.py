import asyncio
import logging
from src.fill_history import download_trades
from src.backtest import Backtester
from src.config import load_config

# Configuration logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("Validation")

async def main():
    print("\n" + "="*50)
    print("🚀 PIPELINE DE VALIDATION (BACKFILL + BACKTEST)")
    print("="*50 + "\n")
    
    # Configuration
    config = load_config()
    symbol = "BTC/USDT" # On peut rendre ça dynamique si besoin
    hours = 24
    
    # Étape 1 : Backfill
    print(f"1️⃣  ÉTAPE 1 : Remplissage de l'historique ({hours}h)")
    try:
        await download_trades(symbol, hours=hours)
    except Exception as e:
        logger.error(f"❌ Échec du backfill : {e}")
        return

    # Étape 2 : Backtest
    print(f"\n2️⃣  ÉTAPE 2 : Exécution du Backtest")
    backtester = Backtester(config)
    
    # On lance le backtest sur le symbole
    # Note: Le backtester va lire les données qu'on vient d'insérer
    await backtester.run(symbol)
    
    print("\n✅ Validation terminée.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Arrêt utilisateur.")
