
import time
import requests
import asyncio
from pybit.unified_trading import HTTP
from telegram import Bot

# === CONFIGURATION ===
BYBIT_API_URL = "https://api.bybit.com"
CANDLE_INTERVAL = "5"  # 5-minute candles
PUMP_THRESHOLD = 1.2  # % change threshold for alert
CHECK_INTERVAL = 60  # seconds

# === TELEGRAM CONFIG ===
TELEGRAM_BOT_TOKEN = "6481536367:AAGH-Y1FB5xmvPPq2v-x0GprQFd5PoDiAto"
TELEGRAM_CHAT_ID = "-1002227838593"

bot = Bot(token=TELEGRAM_BOT_TOKEN)

def get_perpetual_symbols():
    try:
        url = f"{BYBIT_API_URL}/v5/market/instruments-info?category=linear"
        res = requests.get(url).json()
        return [s["symbol"] for s in res["result"]["list"] if s["symbol"].endswith("USDT")]
    except Exception as e:
        print(f"[SYMBOL ERROR] {e}")
        return []

def get_klines(symbol):
    try:
        url = f"{BYBIT_API_URL}/v5/market/kline"
        params = {"symbol": symbol, "interval": CANDLE_INTERVAL, "limit": 2, "category": "linear"}
        res = requests.get(url, params=params).json()
        return res["result"]["list"]
    except Exception as e:
        print(f"[KLINE ERROR] {e}")
        return []

def get_depth(symbol):
    try:
        url = f"{BYBIT_API_URL}/v5/market/orderbook"
        params = {"symbol": symbol, "category": "linear"}
        res = requests.get(url, params=params).json()
        bids = res["result"]["b"]
        asks = res["result"]["a"]
        bid_total = sum(float(x[1]) for x in bids[:5])
        ask_total = sum(float(x[1]) for x in asks[:5])
        return bid_total, ask_total
    except Exception as e:
        print(f"[DEPTH ERROR] {e}")
        return 0, 0

def send_alert(symbol, price, direction, bid, ask):
    emoji = "\U0001F4C8" if direction == "pump" else "\U0001F4C9"
    base = symbol.replace("USDT", "")
    leverage = "x20"
    message = (
        f"\U0001F525 #{base}/USDT ({'Long\U0001F4C8' if direction=='pump' else 'Short\U0001F4C9'}, {leverage}) \U0001F525\n"
        f"Entry - {price:.4f}\n"
        f"Take-Profit:\n"
        f"🥉 TP1 (40%) = {price * (1.015 if direction=='pump' else 0.985):.4f}\n"
        f"🥈 TP2 (60%) = {price * (1.03 if direction=='pump' else 0.97):.4f}\n"
        f"🥇 TP3 (80%) = {price * (1.045 if direction=='pump' else 0.955):.4f}\n"
        f"🚀 TP4 (100%) = {price * (1.06 if direction=='pump' else 0.94):.4f}"
    )
    asyncio.run(bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message))
    print(f"[ALERT SENT] {symbol} - {direction.upper()}")

def check_market():
    symbols = get_perpetual_symbols()
    for symbol in symbols:
        try:
            klines = get_klines(symbol)
            if len(klines) < 2:
                continue
            prev_close = float(klines[-2][4])
            curr_close = float(klines[-1][4])
            change = ((curr_close - prev_close) / prev_close) * 100

            if abs(change) >= PUMP_THRESHOLD:
                bid, ask = get_depth(symbol)
                direction = "pump" if change > 0 else "dump"
                send_alert(symbol, curr_close, direction, bid, ask)

        except Exception as e:
            print(f"[MARKET ERROR] {symbol}: {e}")

# === MAIN LOOP ===
if __name__ == "__main__":
    print("🚀 Market Sniper Bot Running (5-minute candles)...")

    # === TEST ALERT ON STARTUP ===
    try:
        test_message = (
            "\U0001F525 #TESTCOIN/USDT (Long\U0001F4C8, x20) \U0001F525\n"
            "Entry - 0.1234\n"
            "Take-Profit:\n"
            "🥉 TP1 (40%) = 0.1258\n"
            "🥈 TP2 (60%) = 0.1270\n"
            "🥇 TP3 (80%) = 0.1300\n"
            "🚀 TP4 (100%) = 0.1350"
        )
        asyncio.run(bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=test_message))
        print("[TEST ALERT] Sent")
    except Exception as e:
        print(f"[TEST ALERT ERROR] {e}")

    while True:
        check_market()
        time.sleep(CHECK_INTERVAL)





