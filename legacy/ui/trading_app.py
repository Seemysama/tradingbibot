import streamlit as st
import httpx
import json

API_URL = "http://localhost:8000"

st.set_page_config(page_title="Trading Platform", layout="wide")

st.title("🚀 Trading Platform")

# Vérifier la connexion à l'API
try:
    response = httpx.get(f"{API_URL}/health", timeout=5)
    if response.status_code == 200:
        health_data = response.json()
        st.success(f"✅ API Connected - Adapters: {', '.join(health_data.get('adapters', []))}")
    else:
        st.error("❌ API Connection Failed")
except Exception as e:
    st.error(f"❌ API Error: {e}")

# Configuration
try:
    config_response = httpx.get(f"{API_URL}/config", timeout=5)
    if config_response.status_code == 200:
        config = config_response.json()
        st.info(f"📊 Mode: {config['mode']} | Auto-confirm: {config['auto_confirm']} | Risk/Trade: {config['risk_per_trade']*100}%")
except:
    pass

tabs = st.tabs(["🎯 Trading", "📊 Dashboard", "📈 Signals"])

# TAB 1: TRADING
with tabs[0]:
    st.header("🎯 Place Orders")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Order Configuration")
        backend = st.selectbox("Exchange", ["binance_spot", "coinbase_advanced", "kraken_margin"], index=0)
        
        # Adapter le symbole par défaut selon l'exchange
        if backend == "binance_spot":
            default_symbol = "BTCUSDT"
        elif backend == "coinbase_advanced":
            default_symbol = "BTC-USD"
        else:  # kraken_margin
            default_symbol = "XBTUSD"
            
        symbol = st.text_input("Symbol", default_symbol)
        side = st.selectbox("Side", ["buy", "sell"], index=0)
        ord_type = st.selectbox("Order Type", ["market", "limit"], index=0)
        
        if ord_type == "limit":
            price = st.number_input("Price", value=60000.0, help="Limit price")
        else:
            price = None
            
        qty = st.number_input("Quantity", value=0.001, help="Order quantity")
        
        col_sl, col_tp = st.columns(2)
        with col_sl:
            sl = st.number_input("Stop Loss", value=0.0, help="Optional stop loss")
        with col_tp:
            tp = st.number_input("Take Profit", value=0.0, help="Optional take profit")
    
    with col2:
        st.subheader("Order Actions")
        
        if st.button("🔍 Preview Order", type="primary"):
            try:
                preview_data = {
                    "backend": backend,
                    "symbol": symbol,
                    "side": side,
                    "type": ord_type,
                    "qty": qty
                }
                if price:
                    preview_data["price"] = price
                if sl > 0:
                    preview_data["sl"] = sl
                if tp > 0:
                    preview_data["tp"] = tp
                    
                response = httpx.post(f"{API_URL}/preview", json=preview_data, timeout=10)
                
                if response.status_code == 200:
                    result = response.json()
                    st.success("✅ Preview successful!")
                    st.json(result)
                else:
                    st.error(f"❌ Preview failed: {response.text}")
                    
            except Exception as e:
                st.error(f"❌ Error: {e}")
        
        st.write("---")
        
        if st.button("⚡ Execute Order", type="secondary"):
            st.warning("🚨 This will place a REAL order!")
            
        if st.button("🆘 PANIC - Stop All"):
            try:
                response = httpx.post(f"{API_URL}/panic", timeout=10)
                if response.status_code == 200:
                    st.success("🛑 PANIC mode activated!")
                else:
                    st.error("❌ PANIC failed")
            except Exception as e:
                st.error(f"❌ Error: {e}")

# TAB 2: DASHBOARD  
with tabs[1]:
    st.header("📊 Trading Dashboard")
    
    try:
        health_response = httpx.get(f"{API_URL}/health", timeout=5)
        if health_response.status_code == 200:
            health = health_response.json()
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("API Status", "🟢 Online" if health['ok'] else "🔴 Offline")
            with col2:
                st.metric("Adapters", len(health.get('adapters', [])))
            with col3:
                st.metric("Lockout", "🔒 Yes" if health.get('lockout') else "🔓 No")
                
            st.subheader("Available Exchanges")
            for adapter in health.get('adapters', []):
                st.write(f"✅ {adapter}")
                
        # Configuration
        config_response = httpx.get(f"{API_URL}/config", timeout=5)
        if config_response.status_code == 200:
            config = config_response.json()
            
            st.subheader("Risk Configuration")
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Risk per Trade", f"{config['risk_per_trade']*100}%")
                st.metric("Max Leverage", f"{config['max_leverage']}x")
                st.metric("Daily DD Max", f"{config['daily_dd_max']*100}%")
            
            with col2:
                st.metric("Max Concurrent Positions", config['max_concurrent_pos'])
                st.metric("Default SL", f"{config['default_sl_pct']*100}%")
                st.metric("Default TP", f"{config['default_tp_pct']*100}%")
                
    except Exception as e:
        st.error(f"❌ Dashboard error: {e}")

# TAB 3: SIGNALS
with tabs[2]:
    st.header("📈 Trading Signals")
    st.info("Signal analysis and market data will be displayed here")
    
    # Test de validation de symbole
    st.subheader("🔍 Symbol Validation Test")
    test_exchange = st.selectbox("Test Exchange", ["binance", "coinbase", "kraken"])
    test_symbol = st.text_input("Test Symbol", "BTCUSDT")
    
    if st.button("Validate Symbol"):
        try:
            response = httpx.post(f"{API_URL}/validate", 
                                json={"exchange": test_exchange, "symbol": test_symbol}, 
                                timeout=10)
            if response.status_code == 200:
                result = response.json()
                if result.get('valid'):
                    st.success(f"✅ {test_symbol} is valid for {test_exchange}")
                else:
                    st.error(f"❌ {test_symbol} is invalid for {test_exchange}")
                st.json(result)
            else:
                st.error(f"❌ Validation failed: {response.text}")
        except Exception as e:
            st.error(f"❌ Error: {e}")

st.sidebar.header("🔧 Quick Actions")
if st.sidebar.button("🔄 Refresh Status"):
    st.rerun()
    
if st.sidebar.button("📊 Health Check"):
    try:
        response = httpx.get(f"{API_URL}/health", timeout=5)
        st.sidebar.json(response.json())
    except Exception as e:
        st.sidebar.error(f"Error: {e}")
