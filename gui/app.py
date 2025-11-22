import asyncio
import json
from collections import deque
from datetime import datetime

import flet as ft
import httpx
import websockets

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
        self.positions: dict[str, dict] = {}  # symbol -> {side, entry, mark, qty, pnl}
        self.logs = deque(maxlen=200)
        self.last_msg = "-"
        self.connected = False
        self.lockout = False


state = AppState()


async def main(page: ft.Page):
    page.title = "TradingBiBot Cockpit"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 16
    page.bgcolor = "#06070A"
    page.window_width = 1400
    page.window_height = 900

    # --- Widgets simples ---
    status_chip = ft.Text("Déconnecté", color="#A0A0A0", size=12)
    status_led = ft.Container(width=10, height=10, bgcolor="#555", border_radius=5)

    price_text = ft.Text("0.00", size=42, weight=ft.FontWeight.BOLD, font_family="Courier New")
    symbol_input = ft.TextField(label="Symbole", value="BTCUSDT", width=120, dense=True)

    balance_text = ft.Text("$ 10,000.00", size=24, weight=ft.FontWeight.BOLD, font_family="Courier New")
    pnl_text = ft.Text("+0.00%", size=16, color="green", font_family="Courier New")
    positions_count = ft.Text("0 positions", size=12, color="#A0A0A0")

    # --- Chart Equity ---
    chart = ft.LineChart(
        data_series=[
            ft.LineChartData(
                data_points=[ft.LineChartDataPoint(0, 10000)],
                stroke_width=2,
                color="#5CE1E6",
                curved=True,
            )
        ],
        tooltip_bgcolor="#111",
        min_y=9800,
        max_y=10200,
        expand=True,
    )

    # --- Positions Table ---
    positions_table = ft.DataTable(
        heading_row_color="#0F1116",
        columns=[
            ft.DataColumn(ft.Text("Symbol")),
            ft.DataColumn(ft.Text("Side")),
            ft.DataColumn(ft.Text("Entry")),
            ft.DataColumn(ft.Text("Mark")),
            ft.DataColumn(ft.Text("Qty")),
            ft.DataColumn(ft.Text("PnL $")),
        ],
        rows=[],
    )

    # --- Logs ---
    logs_view = ft.ListView(spacing=4, expand=True, auto_scroll=True)

    # --- Actions ---
    qty_input = ft.TextField(label="Taille", value="0.01", width=100, dense=True)

    async def send_order(side: str):
        symbol = symbol_input.value.strip().upper()
        try:
            qty = float(qty_input.value)
        except ValueError:
            logs_view.controls.append(ft.Text("> Quantité invalide", color="red"))
            page.update()
            return

        payload = {"symbol": symbol, "side": side, "qty": qty}
        try:
            async with httpx.AsyncClient() as client:
                await client.post(f"{API_URL}/orders/execute", json=payload, timeout=3.0)
            logs_view.controls.append(ft.Text(f"> Ordre manuel {side} {qty} {symbol}", color="orange"))
            page.update()
        except Exception as e:
            logs_view.controls.append(ft.Text(f"> Erreur envoi ordre: {e}", color="red"))
            page.update()

    async def send_panic(_):
        try:
            async with httpx.AsyncClient() as client:
                await client.post(f"{API_URL}/panic", timeout=3.0)
            state.lockout = True
            panic_btn.text = "LOCKED"
            panic_btn.disabled = True
            panic_btn.bgcolor = "#333"
            page.update()
        except Exception as e:
            logs_view.controls.append(ft.Text(f"> Erreur panic: {e}", color="red"))
            page.update()

    buy_btn = ft.ElevatedButton("BUY", bgcolor="#2ECC71", color="black", on_click=lambda _: asyncio.create_task(send_order("BUY")))
    sell_btn = ft.ElevatedButton("SELL", bgcolor="#E74C3C", color="white", on_click=lambda _: asyncio.create_task(send_order("SELL")))
    panic_btn = ft.ElevatedButton("PANIC", bgcolor="#E67E22", color="black", on_click=send_panic)

    # --- Layout principal ---
    header = ft.Row(
        [
            status_led,
            status_chip,
            ft.Container(expand=True),
            ft.Text("Trading Cockpit", size=16, weight=ft.FontWeight.BOLD),
        ],
        alignment=ft.MainAxisAlignment.START,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    price_card = ft.Container(
        bgcolor="#0F1116",
        border_radius=12,
        padding=16,
        content=ft.Column(
            [
                ft.Row(
                    [ft.Text("Ticker", color="#888"), symbol_input],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                price_text,
                ft.Text(state.last_msg, color="#777", size=10),
            ]
        ),
    )

    stats_card = ft.Container(
        bgcolor="#0F1116",
        border_radius=12,
        padding=16,
        content=ft.Column(
            [
                ft.Row([ft.Text("Equity", color="#888"), balance_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([ft.Text("PnL %", color="#888"), pnl_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                positions_count,
            ]
        ),
    )

    controls_card = ft.Container(
        bgcolor="#0F1116",
        border_radius=12,
        padding=16,
        content=ft.Column(
            [
                ft.Text("Ordres manuels", weight=ft.FontWeight.BOLD),
                ft.Row([symbol_input, qty_input], spacing=8),
                ft.Row([buy_btn, sell_btn, panic_btn], spacing=8),
            ],
            spacing=10,
        ),
    )

    chart_card = ft.Container(
        bgcolor="#0F1116",
        border_radius=12,
        padding=16,
        content=ft.Column([ft.Text("Equity Live", color="#888"), chart]),
        expand=True,
    )

    positions_card = ft.Container(
        bgcolor="#0F1116",
        border_radius=12,
        padding=16,
        content=ft.Column([ft.Text("Positions ouvertes", color="#888"), positions_table], expand=True),
        expand=True,
    )

    logs_card = ft.Container(
        bgcolor="#0B0C0F",
        border_radius=12,
        padding=12,
        height=220,
        content=ft.Column([ft.Text("Logs", color="#888"), logs_view], expand=True),
    )

    page.add(
        header,
        ft.Row([price_card, stats_card, controls_card], spacing=12),
        ft.Row([chart_card, positions_card], spacing=12, expand=True),
        logs_card,
    )

    # --- Rafraîchissement périodique ---
    async def ui_loop():
        while True:
            price_text.value = f"{state.price:,.2f} $"
            balance_text.value = f"$ {state.equity:,.2f}"
            pnl_text.value = f"{state.pnl_pct:+.2f}%"
            pnl_text.color = "#2ECC71" if state.pnl_pct >= 0 else "#E74C3C"

            # Chart
            if state.chart_data:
                vals = [y for _, y in state.chart_data]
                chart.min_y = min(vals) * 0.999
                chart.max_y = max(vals) * 1.001
                chart.data_series[0].data_points = [ft.LineChartDataPoint(x, y) for x, y in state.chart_data]

            # Positions
            rows = []
            for sym, pos in state.positions.items():
                pnl_val = pos.get("pnl", 0.0)
                rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(sym)),
                            ft.DataCell(ft.Text(pos.get("side", ""))),
                            ft.DataCell(ft.Text(f"{pos.get('entry', 0):,.2f}")),
                            ft.DataCell(ft.Text(f"{pos.get('mark', 0):,.2f}")),
                            ft.DataCell(ft.Text(f"{pos.get('qty', 0):,.4f}")),
                            ft.DataCell(ft.Text(f"{pnl_val:,.2f}", color="green" if pnl_val >= 0 else "red")),
                        ]
                    )
                )
            positions_table.rows = rows
            positions_count.value = f"{len(state.positions)} positions"

            # Logs
            while state.logs:
                logs_view.controls.append(state.logs.popleft())
                if len(logs_view.controls) > 200:
                    logs_view.controls.pop(0)

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
                    state.connected = True
                    page.update()

                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                        except json.JSONDecodeError:
                            continue

                        msg_type = data.get("type")

                        if msg_type == "ticker":
                            new_price = float(data.get("price", state.price))
                            state.price = new_price
                            state.last_msg = f"{data.get('symbol', '')} @ {new_price}"

                        elif msg_type == "pnl":
                            state.balance = float(data.get("balance", state.balance))
                            state.equity = float(data.get("equity", state.equity))
                            state.pnl_pct = ((state.equity - 10000) / 10000) * 100
                            idx = len(state.chart_data)
                            state.chart_data.append((idx, state.equity))
                            positions = data.get("positions", [])
                            state.positions = {p["symbol"]: p for p in positions}

                        elif msg_type in ("log", "trade"):
                            txt = data.get("message", "")
                            color = "#A0A0A0"
                            if "BUY" in txt:
                                color = "#2ECC71"
                            elif "SELL" in txt:
                                color = "#E74C3C"
                            elif "CLOSE" in txt:
                                color = "#F39C12"
                            state.logs.append(ft.Text(f"> {txt}", color=color, font_family="Courier New"))
            except Exception:
                status_led.bgcolor = "#E74C3C"
                status_chip.value = "Déconnecté (retry...)"
                state.connected = False
                page.update()
                await asyncio.sleep(2)

    page.run_task(ui_loop)
    await ws_listener()


if __name__ == "__main__":
    ft.app(target=main)
