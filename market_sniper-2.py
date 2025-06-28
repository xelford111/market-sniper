import requests
import time
import pandas as pd
from datetime import datetime, timedelta
from pybit.unified_trading import HTTP

# === CONFIG ===
API_KEY = ""  # Optional, if using private endpoints later
API_SECRET = ""  # Optional
TELEGRAM_BOT_TOKEN = "your_telegram_bot_token_here"
TELEGRAM_CHAT_ID = "your_telegram_chat_id_here"
CHECK_INTERVAL = 300  # 5 minutes
PUMP_THRESHOLD = 1.5  # percent change trigger

session = HTTP(
    testnet=False,
    api_key=API_KEY,
    api_secret=API_SECRET
)

def send_alert(symbol, price, move, bid, ask):
    direction = "Long📈" if move == "pump" else "Short📉"
    emoji = "🔥" if move == "pump" else "⚠️"
    tp1 = round(price * (1.02 if move == "pump" else 0.98), 4)
    tp2 = round(price * (1.04 if move == "pump" else 0.96), 4)
    tp3 = round(price * (1.06 if move == "pump" else 0.94), 4)
    tp4 = round(price * (1.08 if move == "pump" else 0.92), 4)

    message = (
        f"{emoji} <b>#{symbol}/USDT ({direction}, x20)</b> {emoji}\n"
        f"<b>Entry</b> - {price}\n"
        f"<b>Take-Profit:</b>\n"
        f"🥉 TP1 (40%) = {tp1}\n"
        f"🥈 TP2 (60%) = {tp2}\n"
        f"🥇 TP3 (80%) = {tp3}\n"
        f"🚀 TP4 (100%) = {tp4}"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, data=payload)
        print("✅ Sent alert:", symbol, move, "Price:", price)
    except Exception as e:
        print(f"[Telegram ERROR] {e}")

def get_klines(symbol):
    try:
        klines = session.get_kline(
            category="linear",
            symbol=symbol,
            interval="5",
            limit=2
        )["result"]["list"]
        return sorted(klines, key=lambda x: int(x[0]))
    except:
        return []

def get_depth(symbol):
    try:
        depth = session.get_orderbook(category="linear", symbol=symbol)
        bids = float(depth['result']['b'][0][0])
        asks = float(depth['result']['a'][0][0])
        return bids, asks
    except:
        return 0.0, 0.0

def check_market():
    try:
        symbols = session.get_tickers(category="linear")["result"]["list"]
        for s in symbols:
            symbol = s["symbol"]
            if "USDT" not in symbol:
                continue
            klines = get_klines(symbol)
            if len(klines) < 2:
                continue
            prev_close = float(klines[-2][4])
            curr_close = float(klines[-1][4])
            change = ((curr_close - prev_close) / prev_close) * 100

            if abs(change) >= PUMP_THRESHOLD:
                bid, ask = get_depth(symbol)
                move = "pump" if change > 0 else "dump"
                send_alert(symbol, curr_close, move, bid, ask)

    except Exception as e:
        print("[ERROR]", e)

if __name__ == "__main__":
    print("🤖 5-Minute Sniper Bot Running...")

    # === TEST ALERT BLOCK ===
    try:
        test_message = (
            "🔥 <b>#TESTCOIN/USDT (Long📈, x20)</b> 🔥\n"
            "<b>Entry</b> - 0.1234\n"
            "<b>Take-Profit:</b>\n"
            "🥉 TP1 (40%) = 0.1258\n"
            "🥈 TP2 (60%) = 0.1270\n"
            "🥇 TP3 (80%) = 0.1300\n"
            "🚀 TP4 (100%) = 0.1350"
        )
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": test_message, "parse_mode": "HTML"}
        )
        print("✅ [TEST ALERT] Sent successfully.")
    except Exception as e:
        print(f"❌ [TEST ALERT ERROR] {e}")

    while True:
        check_market()
        time.sleep(CHECK_INTERVAL)




