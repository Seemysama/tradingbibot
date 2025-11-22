import asyncio
import sys
from src import config
from src.backtest import Backtester

async def main():
    # Chargement config
    settings = config.load_config()
    
    # Instanciation Backtester
    backtester = Backtester(settings)
    
    # Lancement sur le premier symbole configuré (ex: BTCUSDT)
    symbol = settings.SYMBOLS[0]
    print(f"🧪 Lancement du Backtest sur {symbol}...")
    
    await backtester.run(symbol)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
