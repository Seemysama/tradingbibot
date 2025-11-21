from __future__ import annotations
import os
import asyncio
import streamlit as st
import httpx
import json

API_URL = os.environ.get("API_URL", "http://localhost:8000")

st.set_page_config(page_title="Supervised Trading", layout="wide")

st.title("🚀 Supervised Trading Platform")

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

tabs = st.tabs(["🎯 Trading", "📊 Dashboard", "📈 Signals", "📋 Orders", "⚠️ Risk"])

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
        
        if st.button("⚡ Execute Order", type="secondary"):
            st.warning("🚨 This will place a REAL order!")
            if st.button("✅ Confirm Execute"):
                try:
                    execute_data = {
                        "backend": backend,
                        "symbol": symbol,
                        "side": side,
                        "type": ord_type,
                        "qty": qty
                    }
                    if price:
                        execute_data["price"] = price
                    if sl > 0:
                        execute_data["sl"] = sl
                    if tp > 0:
                        execute_data["tp"] = tp
                        
                    response = httpx.post(f"{API_URL}/execute", json=execute_data, timeout=10)
                    
                    if response.status_code == 200:
                        result = response.json()
                        st.success("✅ Order executed!")
                        st.json(result)
                    else:
                        st.error(f"❌ Execution failed: {response.text}")
                        
                except Exception as e:
                    st.error(f"❌ Error: {e}")
        
        if st.button("🆘 PANIC - Stop All", type="secondary"):
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
                
    except Exception as e:
        st.error(f"❌ Dashboard error: {e}")

# TAB 3: SIGNALS
with tabs[2]:
    st.header("📈 Trading Signals")
    st.info("Signal analysis and market data will be displayed here")
    
    # Placeholder pour les signaux
    st.subheader("Market Overview")
    st.write("Coming soon: Real-time market signals and analysis")

# TAB 4: ORDERS
with tabs[3]:
    st.header("📋 Order Management")
    st.info("Order history and management will be displayed here")
    
    # Placeholder pour les ordres
    st.subheader("Recent Orders")
    st.write("Coming soon: Order history and status tracking")

# TAB 5: RISK
with tabs[4]:
    st.header("⚠️ Risk Management")
    
    try:
        config_response = httpx.get(f"{API_URL}/config", timeout=5)
        if config_response.status_code == 200:
            config = config_response.json()
            
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
        st.error(f"❌ Risk data error: {e}")

st.sidebar.header("🔧 Quick Actions")
st.sidebar.button("🔄 Refresh Data")
st.sidebar.button("📊 Health Check")
st.sidebar.button("⚙️ Settings")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{API_URL}/orders/execute",
            json={
                "backend": backend,
                "symbol": symbol,
                "side": side,
                "type": ord_type,
                "price": price or None,
                "sl": sl or None,
                "tp": tp or None,
                "qty": qty or None,
            },
        )
        if resp.status_code != 200:
            execution_result.error(f"Execute error {resp.status_code}: {resp.text}")
        else:
            execution_result.json(resp.json())

async def do_panic():  # type: ignore[no-untyped-def]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{API_URL}/panic")
        if resp.status_code != 200:
            st.error(f"Panic error {resp.status_code}: {resp.text}")
        else:
            st.warning("PANIC triggered; lockout active")

    if col_prev.button("PREVIEW"):
        asyncio.run(do_preview())
    if col_exec.button("EXECUTE"):
        asyncio.run(do_execute())
    if col_panic.button("PANIC", type="primary"):
        asyncio.run(do_panic())

with tabs[0]:
    st.subheader("Dashboard")
    # Badges
    lock = st.session_state.get("risk_status", {}).get("lockout")
    mode = os.environ.get("MODE", "PAPER")
    st.markdown(f"**Mode:** {mode} | **Lockout:** {lock}")
    # Equity placeholder
    if st.button("Refresh Equity"):
        async def _riskdash():  # type: ignore[no-untyped-def]
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{API_URL}/risk/status")
                if r.status_code == 200:
                    st.session_state["risk_status"] = r.json()
        asyncio.run(_riskdash())
    st.json(st.session_state.get("risk_status", {}))

with tabs[2]:
    st.subheader("Open Positions")
    if st.button("Refresh Positions"):
        async def _load_pos():  # type: ignore[no-untyped-def]
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{API_URL}/positions")
                if r.status_code == 200:
                    st.session_state["positions_data"] = r.json()
        asyncio.run(_load_pos())
    st.dataframe(st.session_state.get("positions_data", []))

with tabs[3]:
    st.subheader("Orders")
    if st.button("Refresh Orders"):
        async def _load_ord():  # type: ignore[no-untyped-def]
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{API_URL}/orders")
                if r.status_code == 200:
                    st.session_state["orders_data"] = r.json()
        asyncio.run(_load_ord())
    for o in st.session_state.get("orders_data", []):
        st.json(o)

with tabs[4]:
    st.subheader("Risk Status")
    async def _risk():  # type: ignore[no-untyped-def]
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{API_URL}/risk/status")
            if r.status_code == 200:
                st.session_state["risk_status"] = r.json()
    if st.button("Refresh Risk"):
        asyncio.run(_risk())
    st.json(st.session_state.get("risk_status", {}))
