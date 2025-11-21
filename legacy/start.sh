#!/bin/bash

# 🚀 TradingBiBot - Quick Start Script
echo "🚀 TradingBiBot Quick Start"
echo "=============================="

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source .venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install -q -r requirements.txt

# Check for .env file
if [ ! -f ".env" ]; then
    echo "⚠️  No .env file found. Copying from .env.example..."
    cp .env.example .env
    echo "📝 Please edit .env with your API keys before continuing!"
    echo "   Example: nano .env"
    echo ""
    echo "For testing without real APIs, you can use PAPER mode:"
    echo "   MODE=PAPER"
    echo "   REAL_ADAPTERS=0"
    echo ""
    read -p "Press Enter after editing .env (or to continue with PAPER mode)..."
fi

# Run tests
echo "🧪 Running tests..."
python -m pytest -v

if [ $? -eq 0 ]; then
    echo "✅ All tests passed!"
    
    # Start services
    echo ""
    echo "🚀 Starting services..."
    echo "📡 API Server: http://localhost:8000"
    echo "🌐 Web Interface: http://localhost:8501"
    echo "📚 API Docs: http://localhost:8000/docs"
    echo ""
    echo "Starting in 3 seconds..."
    sleep 3
    
    # Start API server in background
    echo "Starting API server..."
    uvicorn api.server:app --host 127.0.0.1 --port 8000 &
    API_PID=$!
    
    # Wait a moment for API to start
    sleep 3
    
    # Start Streamlit interface
    echo "Starting Web interface..."
    streamlit run ui/trading_app.py --server.port 8501 &
    UI_PID=$!
    
    echo ""
    echo "✅ Services started!"
    echo "API PID: $API_PID"
    echo "UI PID: $UI_PID"
    echo ""
    echo "🌐 Open http://localhost:8501 to start trading!"
    echo ""
    echo "Press Ctrl+C to stop all services..."
    
    # Wait for interrupt
    trap "echo '🛑 Stopping services...'; kill $API_PID $UI_PID 2>/dev/null; exit" INT
    wait
    
else
    echo "❌ Tests failed! Please fix issues before starting."
    exit 1
fi
