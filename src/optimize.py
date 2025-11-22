import time
import pandas as pd
from tabulate import tabulate
from src.analytics import VectorBacktester

def optimize():
    print("\n" + "="*60)
    print("🔬 OPTIMISATION DE STRATÉGIE (GRID SEARCH)")
    print("="*60 + "\n")

    # 1. Initialisation et Chargement des données
    print("📥 Chargement des données haute fréquence (1m)...")
    backtester = VectorBacktester(symbol="BTC/USDT")
    try:
        backtester.load_data(hours=24)
        if backtester.df_1m is None or backtester.df_1m.empty:
            print("❌ Erreur: Pas de données chargées.")
            return
        print(f"✅ {len(backtester.df_1m)} bougies chargées.")
    except Exception as e:
        print(f"❌ Erreur de connexion/chargement: {e}")
        return

    # 2. Définition de la grille de recherche
    timeframes = ['1m', '5m', '15m', '1h', '4h']
    fast_periods = [5, 10, 20, 50]
    slow_periods = [20, 50, 100, 200]
    
    results = []
    start_time = time.time()
    
    print(f"\n🚀 Lancement du Grid Search ({len(timeframes) * len(fast_periods) * len(slow_periods)} combinaisons)...")

    # 3. Exécution de la grille
    # On pré-calcule les resamples pour éviter de le faire à chaque itération
    resampled_data = {}
    for tf in timeframes:
        try:
            resampled_data[tf] = backtester.resample(tf)
        except Exception as e:
            print(f"⚠️ Impossible de resample en {tf}: {e}")

    count = 0
    for tf, df in resampled_data.items():
        if df.empty:
            continue
            
        for fast in fast_periods:
            for slow in slow_periods:
                if fast >= slow:
                    continue # La période rapide doit être inférieure à la lente
                
                stats = backtester.run(df, fast, slow)
                
                results.append({
                    'Timeframe': tf,
                    'Fast': fast,
                    'Slow': slow,
                    'PnL %': stats['return_pct'],
                    'Drawdown %': stats['max_drawdown_pct'],
                    'Trades': stats['num_trades']
                })
                count += 1

    duration = time.time() - start_time
    print(f"✅ {count} tests effectués en {duration:.2f} secondes.\n")

    # 4. Analyse et Affichage
    if not results:
        print("⚠️ Aucun résultat valide.")
        return

    df_results = pd.DataFrame(results)
    
    # Tri par PnL décroissant
    top_10 = df_results.sort_values(by='PnL %', ascending=False).head(10)
    
    print("🏆 TOP 10 CONFIGURATIONS :")
    print(tabulate(top_10, headers='keys', tablefmt='pretty', showindex=False, floatfmt=".2f"))
    
    # Meilleure config absolue
    best = top_10.iloc[0]
    print(f"\n💡 RECOMMANDATION : Utiliser TF={best['Timeframe']}, Fast={int(best['Fast'])}, Slow={int(best['Slow'])}")

if __name__ == "__main__":
    optimize()
