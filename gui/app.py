import flet as ft
import websockets
import asyncio
import json
import httpx
from collections import deque
from datetime import datetime
import os

# Endpoints locaux
API_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000/ws/logs"

# Rythme de rafraîchissement UI (s)
REFRESH_RATE = 0.5

class AppState:
    """État partagé entre WebSocket et rafraîchissement UI."""
    def __init__(self):
        self.price = 0.0
        self.balance = 10000.0
        self.equity = 10000.0
        self.pnl_pct = 0.0
        self.chart_data = deque(maxlen=240)  # 2 minutes @ 500ms
        self.positions: dict[str, dict] = {}
        self.logs = deque(maxlen=500)
        self.last_msg = "-"
        self.connected = False
        self.lockout = False
        self.selected_symbol = "BTCUSDT"

state = AppState()

async def main(page: ft.Page):
    page.title = "TradingBiBot Cockpit - FR"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 16
    page.bgcolor = "#06070A"
    page.window_width = 1400
    page.window_height = 900
    
    # Polices
    page.fonts = {"Mono": "Roboto Mono, Consolas, monospace"}

    # --- Widgets ---
    status_chip = ft.Text("Déconnecté", color="#A0A0A0", size=12)
    status_led = ft.Container(width=10, height=10, bgcolor="#555", border_radius=5)
    
    price_text = ft.Text("0.00 $", size=42, weight=ft.FontWeight.BOLD, font_family="Mono")
    
    def on_symbol_change(e):
        state.selected_symbol = symbol_input.value.strip().upper() or "BTCUSDT"
    symbol_input = ft.TextField(label="Symbole", value="BTCUSDT", width=120, dense=True, text_size=12, on_change=on_symbol_change)
    
    balance_text = ft.Text("$ 10,000.00", size=24, weight=ft.FontWeight.BOLD, font_family="Mono")
    pnl_text = ft.Text("+0.00%", size=16, color="green", font_family="Mono")
    positions_count = ft.Text("0 positions", size=12, color="#A0A0A0")

    # --- Chart Equity (Amélioré) ---
    chart_series = ft.LineChartData(
        data_points=[ft.LineChartDataPoint(0, 10000)],
        stroke_width=2,
        color="#5CE1E6",
        curved=True,
        stroke_cap_round=True,
        point=False,
    )
    chart = ft.LineChart(
        data_series=[chart_series],
        tooltip_bgcolor="#111",
        min_y=9800,
        max_y=10200,
        expand=True,
        left_axis=ft.ChartAxis(labels_size=40),
        bottom_axis=ft.ChartAxis(labels_size=30, labels=[]),
    )

    # --- Positions Table ---
    positions_table = ft.DataTable(
        heading_row_color="#0F1116",
        columns=[
            ft.DataColumn(ft.Text("Symbole")),
            ft.DataColumn(ft.Text("Sens")),
            ft.DataColumn(ft.Text("Entrée")),
            ft.DataColumn(ft.Text("Prix Actuel")),
            ft.DataColumn(ft.Text("Taille")),
            ft.DataColumn(ft.Text("PnL $")),
        ],
        rows=[],
    )

    # --- Logs ---
    logs_view = ft.ListView(spacing=2, expand=True, auto_scroll=True)

    # --- Actions (Export Logs) ---
    def export_logs(e):
        # Concatène les logs et les copie dans le presse-papiers (mac/desktop)
        buffer = "\n".join([log_line.value for log_line in state.logs])
        try:
            page.set_clipboard(buffer)
            page.show_snack_bar(ft.SnackBar(content=ft.Text("Logs copiés dans le presse-papiers")))
        except Exception as err:
            page.show_snack_bar(ft.SnackBar(content=ft.Text(f"Impossible de copier les logs: {err}")))

    export_btn = ft.ElevatedButton("💾 Exporter Logs", on_click=export_logs, height=30)

    # --- Actions Trading ---
    qty_input = ft.TextField(label="Taille", value="0.01", width=100, dense=True)

    async def send_order(side: str):
        symbol = symbol_input.value.strip().upper()
        try:
            qty = float(qty_input.value)
        except ValueError:
            return

        payload = {"symbol": symbol, "side": side, "qty": qty}
        try:
            async with httpx.AsyncClient() as client:
                await client.post(f"{API_URL}/orders/execute", json=payload, timeout=3.0)
            add_log(f"⚠️ ORDRE MANUEL ENVOYÉ: {side} {qty} {symbol}", color="orange")
        except Exception as e:
            add_log(f"❌ Erreur envoi: {e}", color="red")

    async def send_panic(_):
        try:
            async with httpx.AsyncClient() as client:
                await client.post(f"{API_URL}/panic", timeout=3.0)
            state.lockout = True
            panic_btn.text = "VERROUILLÉ"
            panic_btn.disabled = True
            panic_btn.bgcolor = "#333"
            page.update()
        except Exception as e:
            add_log(f"❌ Erreur panic: {e}", color="red")

    buy_btn = ft.ElevatedButton("ACHETER", bgcolor="#2ECC71", color="black", on_click=lambda _: asyncio.create_task(send_order("BUY")))
    sell_btn = ft.ElevatedButton("VENDRE", bgcolor="#E74C3C", color="white", on_click=lambda _: asyncio.create_task(send_order("SELL")))
    panic_btn = ft.ElevatedButton("PANIC", bgcolor="#E67E22", color="black", on_click=send_panic)

    # --- Helper Logs ---
    def add_log(message: str, color: str = "#e0e0e0"):
        ts = datetime.now().strftime("%H:%M:%S")
        line = ft.Text(f"[{ts}] {message}", color=color, font_family="Mono", size=12, selectable=True)
        state.logs.append(line)
        logs_view.controls.append(line)
        if len(logs_view.controls) > 500:
            logs_view.controls.pop(0)
        page.update()

    # --- Layout ---
    header = ft.Row(
        [
            status_led, status_chip,
            ft.Container(expand=True),
            ft.Text("Trading Cockpit", size=16, weight=ft.FontWeight.BOLD),
        ],
        alignment=ft.MainAxisAlignment.START,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    price_card = ft.Container(
        bgcolor="#0F1116", border_radius=12, padding=16,
        content=ft.Column([
            ft.Row([ft.Text("Symbole", color="#888"), symbol_input], alignment="spaceBetween"),
            price_text,
            ft.Text(state.last_msg, color="#777", size=10),
        ]),
    )

    stats_card = ft.Container(
        bgcolor="#0F1116", border_radius=12, padding=16,
        content=ft.Column([
            ft.Row([ft.Text("Capital", color="#888"), balance_text], alignment="spaceBetween"),
            ft.Row([ft.Text("PnL %", color="#888"), pnl_text], alignment="spaceBetween"),
            positions_count,
        ]),
    )

    controls_card = ft.Container(
        bgcolor="#0F1116", border_radius=12, padding=16,
        content=ft.Column([
            ft.Text("Ordres manuels", weight="bold"),
            ft.Row([symbol_input, qty_input], spacing=8),
            ft.Row([buy_btn, sell_btn, panic_btn], spacing=8),
        ], spacing=10),
    )

    chart_card = ft.Container(
        bgcolor="#0F1116", border_radius=12, padding=16,
        content=ft.Column([ft.Text("Évolution Equity", color="#888"), chart]),
        expand=True,
    )

    positions_card = ft.Container(
        bgcolor="#0F1116", border_radius=12, padding=16,
        content=ft.Column([ft.Text("Positions Ouvertes", color="#888"), positions_table], expand=True),
        expand=True,
    )

    logs_card = ft.Container(
        bgcolor="#0B0C0F", border_radius=12, padding=12, height=250,
        content=ft.Column([
            ft.Row([ft.Text("Journal Système", color="#888"), export_btn], alignment="spaceBetween"),
            logs_view
        ], expand=True),
    )

    page.add(
        header,
        ft.Row([price_card, stats_card, controls_card], spacing=12),
        ft.Row([chart_card, positions_card], spacing=12, expand=True),
        logs_card,
    )

    # --- UI Loop ---
    async def ui_loop():
        while True:
            price_text.value = f"{state.price:,.2f} $"
            balance_text.value = f"$ {state.equity:,.2f}"
            pnl_text.value = f"{state.pnl_pct:+.2f}%"
            pnl_text.color = "#2ECC71" if state.pnl_pct >= 0 else "#E74C3C"

            if state.chart_data:
                vals = [y for _, y in state.chart_data]
                # Mise à jour des points (index séquentiels)
                chart_series.data_points = [
                    ft.LineChartDataPoint(i, y) for i, (_, y) in enumerate(state.chart_data)
                ]
                # Axes dynamiques
                chart.min_y = min(vals) * 0.999
                chart.max_y = max(vals) * 1.001
                # Labels heure toutes les ~10 minutes (si dispo)
                labels = []
                for idx, (ts, _) in enumerate(state.chart_data):
                    if idx == 0:
                        labels.append(ft.ChartAxisLabel(value=idx, label=ft.Text(ts)))
                    else:
                        try:
                            dt = datetime.strptime(ts, "%H:%M")
                            if dt.minute % 10 == 0:
                                labels.append(ft.ChartAxisLabel(value=idx, label=ft.Text(ts)))
                        except Exception:
                            pass
                chart.bottom_axis = ft.ChartAxis(labels_size=30, labels=labels)

            rows = []
            for sym, pos in state.positions.items():
                pnl_val = pos.get("pnl", 0.0)
                rows.append(ft.DataRow(cells=[
                    ft.DataCell(ft.Text(sym)),
                    ft.DataCell(ft.Text(pos.get("side", ""))),
                    ft.DataCell(ft.Text(f"{pos.get('entry', 0):,.2f}")),
                    ft.DataCell(ft.Text(f"{pos.get('mark', 0):,.2f}")),
                    ft.DataCell(ft.Text(f"{pos.get('qty', 0):,.4f}")),
                    ft.DataCell(ft.Text(f"{pnl_val:,.2f} $", color="green" if pnl_val >= 0 else "red")),
                ]))
            positions_table.rows = rows
            positions_count.value = f"{len(state.positions)} positions"

            page.update()
            await asyncio.sleep(REFRESH_RATE)

    # --- WebSocket Listener ---
    async def ws_listener():
        while True:
            try:
                status_led.bgcolor = "#CC8400"
                status_chip.value = "Connexion..."
                page.update()
                
                async with websockets.connect(WS_URL) as ws:
                    status_led.bgcolor = "#2ECC71"
                    status_chip.value = "Connecté"
                    page.update()
                    
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                            msg_type = data.get("type")

                            if msg_type == "ticker":
                                symbol = str(data.get("symbol", "")).upper()
                                if symbol == state.selected_symbol:
                                    state.price = float(data.get("price", state.price))
                                    state.last_msg = f"{symbol} @ {state.price}"

                            elif msg_type == "pnl":
                                state.balance = float(data.get("balance", state.balance))
                                state.equity = float(data.get("equity", state.equity))
                                state.pnl_pct = ((state.equity - 10000) / 10000) * 100
                                now_str = datetime.now().strftime("%H:%M")
                                # Filtre anti-outlier (>50% vs dernier point)
                                if state.chart_data:
                                    last_val = state.chart_data[-1][1]
                                    if last_val > 0 and abs(state.equity - last_val) / last_val > 0.5:
                                        continue
                                state.chart_data.append((now_str, state.equity))
                                positions = data.get("positions", [])
                                state.positions = {p["symbol"]: p for p in positions}

                            elif msg_type in ("log", "trade"):
                                txt = data.get("message", "")
                                color = "#A0A0A0"
                                if "BUY" in txt: color = "#2ECC71"
                                elif "SELL" in txt: color = "#E74C3C"
                                elif "CLOSE" in txt: color = "#F39C12"
                                add_log(txt, color)

                        except json.JSONDecodeError:
                            pass
            except Exception:
                status_led.bgcolor = "#E74C3C"
                status_chip.value = "Déconnecté (retry...)"
                page.update()
                await asyncio.sleep(2)

    page.run_task(ui_loop)
    await ws_listener()

if __name__ == "__main__":
    ft.app(target=main)
