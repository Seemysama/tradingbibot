import flet as ft
import websockets
import asyncio
import httpx
import re
from datetime import datetime

# Configuration
API_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000/ws/logs"

# Styles
COLOR_BG = "#0a0a0a"       # Noir profond
COLOR_SURFACE = "#111111"  # Gris très sombre
COLOR_BORDER = "#333333"
COLOR_ACCENT = "#00ff9d"   # Vert Cyberpunk
COLOR_DANGER = "#ff0055"   # Rouge Cyberpunk
COLOR_TEXT = "#e0e0e0"
FONT_MONO = "Courier New"

async def main(page: ft.Page):
    page.title = "TRADING COCKPIT v1.0"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = COLOR_BG
    page.padding = 0
    page.window_width = 1200
    page.window_height = 800

    # --- État ---
    pnl_value = ft.Text("0.00 $", size=24, weight="bold", color=COLOR_ACCENT, font_family=FONT_MONO)
    
    # --- Composants UI ---

    # 1. Console de Logs (Terminal Style)
    logs_list = ft.ListView(
        expand=True,
        spacing=2,
        padding=20,
        auto_scroll=True,
        divider_thickness=0
    )

    log_container = ft.Container(
        content=logs_list,
        expand=True,
        bgcolor=COLOR_SURFACE,
        border=ft.border.all(1, COLOR_BORDER),
        margin=10,
        border_radius=5
    )

    # 2. Header (Monitoring)
    header = ft.Container(
        content=ft.Row([
            ft.Row([
                ft.Icon(name="terminal", color=COLOR_ACCENT),
                ft.Text("SYSTEM_STATUS: ONLINE", color=COLOR_ACCENT, font_family=FONT_MONO, weight="bold")
            ]),
            ft.Row([
                ft.Text("SESSION PNL:", color="grey", font_family=FONT_MONO),
                pnl_value
            ])
        ], alignment="spaceBetween"),
        padding=ft.padding.symmetric(horizontal=20, vertical=15),
        bgcolor=COLOR_SURFACE,
        border=ft.border.only(bottom=ft.border.BorderSide(1, COLOR_BORDER))
    )

    # 3. Footer (Contrôles)
    async def trigger_panic(e):
        btn_panic.content = ft.ProgressRing(width=20, height=20, color="white")
        btn_panic.disabled = True
        page.update()
        try:
            async with httpx.AsyncClient() as client:
                await client.post(f"{API_URL}/panic", timeout=2.0)
                add_log("🚨 PANIC SIGNAL SENT TO CORE ENGINE", COLOR_DANGER)
        except Exception as ex:
            add_log(f"❌ ERROR SENDING PANIC: {ex}", "red")
        finally:
            btn_panic.content = ft.Text("KILL SWITCH (PANIC)", size=16, weight="bold")
            btn_panic.disabled = False
            page.update()

    async def trigger_buy(e):
        try:
            payload = {"symbol": "BTCUSDT", "side": "BUY", "qty": 0.01, "type": "MARKET"}
            async with httpx.AsyncClient() as client:
                await client.post(f"{API_URL}/orders/execute", json=payload)
        except Exception as ex:
            add_log(f"❌ ERROR: {ex}", "red")

    btn_panic = ft.ElevatedButton(
        content=ft.Text("KILL SWITCH (PANIC)", size=16, weight="bold"),
        style=ft.ButtonStyle(
            color="white",
            bgcolor=COLOR_DANGER,
            shape=ft.RoundedRectangleBorder(radius=5),
            padding=20
        ),
        width=250,
        on_click=trigger_panic
    )

    btn_buy_test = ft.OutlinedButton(
        "TEST BUY 0.01 BTC",
        style=ft.ButtonStyle(color=COLOR_ACCENT, shape=ft.RoundedRectangleBorder(radius=5)),
        on_click=trigger_buy
    )

    footer = ft.Container(
        content=ft.Row([
            ft.Text("CONTROLS >", font_family=FONT_MONO, color="grey"),
            btn_buy_test,
            ft.Container(expand=True), # Spacer
            btn_panic
        ], alignment="spaceBetween"),
        padding=20,
        bgcolor=COLOR_SURFACE,
        border=ft.border.only(top=ft.border.BorderSide(1, COLOR_BORDER))
    )

    # --- Logique ---

    def add_log(message: str, color: str = COLOR_TEXT):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        logs_list.controls.append(
            ft.Text(f"[{timestamp}] {message}", color=color, font_family=FONT_MONO, size=12, selectable=True)
        )
        # Limite l'historique pour la performance
        if len(logs_list.controls) > 500:
            logs_list.controls.pop(0)
        page.update()

    def parse_pnl(message: str):
        # Cherche un pattern type "PnL: 12.50" ou "PnL: -5.00"
        match = re.search(r"PnL:\s*([+-]?\d+\.?\d*)", message)
        if match:
            val = float(match.group(1))
            pnl_value.value = f"{val:+.2f} $"
            pnl_value.color = COLOR_ACCENT if val >= 0 else COLOR_DANGER
            page.update()

    async def websocket_loop():
        while True:
            try:
                add_log("Connecting to Neural Link...", "grey")
                async with websockets.connect(WS_URL) as ws:
                    add_log("✅ LINK ESTABLISHED. LISTENING...", COLOR_ACCENT)
                    while True:
                        msg = await ws.recv()
                        
                        # Parsing couleur
                        color = COLOR_TEXT
                        if "BUY" in msg: color = COLOR_ACCENT
                        elif "SELL" in msg: color = COLOR_DANGER
                        elif "SIGNAL" in msg: color = "yellow"
                        elif "PANIC" in msg: color = "red"
                        elif "ORDRE" in msg: color = "cyan"
                        
                        add_log(msg, color)
                        parse_pnl(msg)
                        
            except Exception as e:
                add_log(f"⚠️ LINK LOST: {e}. Retrying in 3s...", "grey")
                await asyncio.sleep(3)

    # --- Assemblage ---
    page.add(
        ft.Column([
            header,
            log_container,
            footer
        ], expand=True, spacing=0)
    )

    # Lancement tâche de fond
    page.run_task(websocket_loop)

if __name__ == "__main__":
    print("🚀 Lancement du Dashboard Flet (Mode Web)...")
    # Force l'ouverture dans le navigateur pour éviter les problèmes de fenêtre native
    ft.app(target=main, view=ft.AppView.WEB_BROWSER)
