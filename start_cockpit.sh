#!/bin/bash

# Activation de l'environnement virtuel
source .venv/bin/activate

echo "🛑 Arrêt des processus existants..."
pkill -f "uvicorn api.server:app"
pkill -f "python main.py"
pkill -f "python gui/app.py"
sleep 2

echo "🚀 Démarrage du Trading Cockpit..."

# 1. Démarrer l'API Server
echo "📡 Démarrage de l'API Server..."
uvicorn api.server:app --host 127.0.0.1 --port 8000 > api.log 2>&1 &
API_PID=$!
echo "   -> API PID: $API_PID"
sleep 2

# 2. Démarrer le Bot de Trading
echo "🤖 Démarrage du Bot..."
python main.py > bot.log 2>&1 &
BOT_PID=$!
echo "   -> Bot PID: $BOT_PID"
sleep 2

# 3. Démarrer l'Interface Graphique (Flet)
echo "🖥️  Démarrage de l'Interface..."
python gui/app.py &
GUI_PID=$!
echo "   -> GUI PID: $GUI_PID"

echo "✅ Tout est lancé !"
echo "   - API Logs: tail -f api.log"
echo "   - Bot Logs: tail -f bot.log"
echo "   - Pour arrêter: Ctrl+C"

# Gestion de l'arrêt propre
trap "kill $API_PID $BOT_PID $GUI_PID; exit" INT
wait
