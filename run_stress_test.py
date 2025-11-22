import asyncio
import logging
import pandas as pd
from tabulate import tabulate
from src.fill_history import download_trades
from src.analytics import VectorBacktester

# Configuration logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("StressTest")

async def run_stress_test():
    """
    Exécute un Stress Test complet sur 30 jours.
    1. Backfill des données (30 jours)
    2. Grid Search sur les paramètres SMA
    3. Analyse de robustesse
    """
    SYMBOL = "BTC/USDT"
    DAYS = 30
    HOURS = DAYS * 24
    
    print(f"\n🚀 Démarrage du Stress Test : {SYMBOL} sur {DAYS} jours\n")
    print("="*60)

    # 1. Backfill Massif
    logger.info(f"📥 Étape 1/3 : Téléchargement de l'historique ({DAYS} jours)...")
    try:
        # On utilise la fonction existante de fill_history
        # Note: download_trades utilise '1m' par défaut dans le code actuel
        await download_trades(symbol=SYMBOL, hours=HOURS)
    except Exception as e:
        logger.error(f"❌ Erreur Backfill: {e}")
        return

    # 2. Initialisation Backtester
    logger.info("⚙️  Étape 2/3 : Chargement des données en mémoire...")
    try:
        backtester = VectorBacktester(symbol=SYMBOL)
        backtester.load_data(hours=HOURS)
        
        if backtester.df_1m is None or backtester.df_1m.empty:
            logger.error("❌ Aucune donnée chargée. Vérifiez QuestDB.")
            return
            
        logger.info(f"✅ Données chargées : {len(backtester.df_1m)} bougies 1m.")
    except Exception as e:
        logger.error(f"❌ Erreur Chargement Données: {e}")
        return

    # 3. Grid Search
    logger.info("🔬 Étape 3/3 : Exécution du Grid Search...")
    
    # Paramètres à tester
    timeframes = ['1m', '5m', '15m', '1h']
    fast_smas = [5, 10, 20]
    slow_smas = [50, 100, 200]
    
    results = []
    
    # Configuration actuelle (Golden)
    current_config = {'tf': '1m', 'fast': 5, 'slow': 200}
    current_perf = None

    total_iterations = len(timeframes) * len(fast_smas) * len(slow_smas)
    iteration = 0

    for tf in timeframes:
        # Resampling une seule fois par timeframe
        try:
            df_tf = backtester.resample(tf)
        except Exception as e:
            logger.warning(f"⚠️ Skip timeframe {tf}: {e}")
            continue
            
        for fast in fast_smas:
            for slow in slow_smas:
                if fast >= slow:
                    continue # Skip invalid configs
                
                iteration += 1
                # print(f"\r   Progression : {iteration}/{total_iterations}", end="")
                
                try:
                    stats = backtester.run(df_tf, fast_period=fast, slow_period=slow)
                    
                    res = {
                        'Timeframe': tf,
                        'Fast': fast,
                        'Slow': slow,
                        'Return %': round(stats['return_pct'], 2),
                        'Max DD %': round(stats['max_drawdown_pct'], 2),
                        'Trades': stats['num_trades']
                    }
                    results.append(res)
                    
                    # Check Golden Config
                    if tf == current_config['tf'] and fast == current_config['fast'] and slow == current_config['slow']:
                        current_perf = res
                        
                except Exception as e:
                    logger.error(f"❌ Erreur config {tf}/{fast}/{slow}: {e}")

    print("\n" + "="*60)
    print("📊 RÉSULTATS DU STRESS TEST")
    print("="*60)

    # Tri par rendement
    df_results = pd.DataFrame(results)
    if df_results.empty:
        logger.error("❌ Aucun résultat généré.")
        return

    df_results = df_results.sort_values(by='Return %', ascending=False)
    
    print("\n🏆 TOP 5 CONFIGURATIONS :")
    print(tabulate(df_results.head(5), headers="keys", tablefmt="pretty", showindex=False))

    print("\n🔍 ANALYSE CONFIGURATION ACTUELLE (Golden Cross 1m/5/200) :")
    if current_perf:
        headers = list(current_perf.keys())
        values = [list(current_perf.values())]
        print(tabulate(values, headers=headers, tablefmt="pretty"))
        
        # Vérification Robustesse
        is_robust = True
        warnings = []
        
        if current_perf['Return %'] < 0:
            is_robust = False
            warnings.append("❌ Stratégie perdante sur 30 jours.")
            
        if current_perf['Max DD %'] < -20:
            is_robust = False
            warnings.append(f"❌ Drawdown critique ({current_perf['Max DD %']}%) > -20%")
            
        if is_robust:
            print("\n✅ CONCLUSION : La stratégie est ROBUSTE sur 30 jours.")
        else:
            print("\n⚠️ CONCLUSION : La stratégie présente des FAIBLESSES.")
            for w in warnings:
                print(f"   - {w}")
    else:
        print("❌ Configuration actuelle non trouvée dans les résultats.")

if __name__ == "__main__":
    asyncio.run(run_stress_test())
