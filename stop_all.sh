#!/bin/bash
echo "🛑 Arrêt brutal de tous les processus Python..."
pkill -9 -f "python main.py"
pkill -9 -f "uvicorn api.server:app"
pkill -9 -f "python gui/app.py"
pkill -9 -f "streamlit"
echo "✅ Tous les processus ont été tués."
