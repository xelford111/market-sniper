import time
import requests
import pandas as pd

TELEGRAM_BOT_TOKEN = 'YOUR_BOT_TOKEN_HERE'
TELEGRAM_CHAT_ID = 'YOUR_CHAT_ID_HERE'

CHECK_INTERVAL = 300  # 5 minutes = 300 seconds
PUMP_THRESHOLD = 2.0  # % change for signal

BYBIT_ENDPOINT = "https://api.bybit.com/v5/market/kline"
DEPTH_ENDPOINT = "https://api.bybit.com/v5/market/orderbook"

# === Send Alert to Telegram ===
def send_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")

# === Fetch 5-min Candle ===
def fetch_klines(symbol):
    try:
        params = {
            "category": "linear",
            "symbol": symbol,
            "interval": "5",
            "limit": 2,
        }
        res = requests.get(BYBIT_ENDPOINT, params=params)
        res.raise_for_status()
        return res.json()["result"]["list"]
    except Exception as e:
        print(f"[KLINE ERROR] {symbol}: {e}")
        return None

# === Fetch Order Book ===
def get_depth(symbol):
    try:
        params = {"category": "linear", "symbol": symbol}
        res = requests.get(DEPTH_ENDPOINT, params=params)
        res.raise_for_status()
        data = res.json()["result"]
        bid = float(data["b"][0][0])
        ask = float(data["a"][0][0])
        return bid, ask
    except Exception as e:
        print(f"[DEPTH ERROR] {symbol}: {e}")
        return 0, 0

# === Compose and Send Signal ===
def send_trade_alert(symbol, close_price, direction, bid, ask):
    entry = float(close_price)
    tp1 = round(entry * 1.01, 4)
    tp2 = round(entry * 1.02, 4)
    tp3 = round(entry * 1.03, 4)
    tp4 = round(entry * 1.05, 4)

    emoji = "📈" if direction == "pump" else "📉"

    message = (
        f"🔥 <b>#{symbol}/USDT ({'Long' if direction == 'pump' else 'Short'} {emoji}, x20)</b> 🔥\n"
        f"<b>Entry</b> - {entry}\n"
        f"<b>Take-Profit:</b>\n"
        f"🥉 TP1 (40%) - {tp1}\n"
        f"🥈 TP2 (60%) - {tp2}\n"
        f"🥇 TP3 (80%) - {tp3}\n"
        f"🚀 TP4 (100%) - {tp4}"
    )
    send_alert(message)

# === Scan Market ===
def check_market():
    symbols = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT"]  # Add more if desired

    for symbol in symbols:
        try:
            klines = fetch_klines(symbol)
            if not klines:
                continue
            prev_close = float(klines[-2][4])
            curr_close = float(klines[-1][4])
            change = ((curr_close - prev_close) / prev_close) * 100

            if abs(change) >= PUMP_THRESHOLD:
                bid, ask = get_depth(symbol)
                direction = "pump" if change > 0 else "dump"
                send_trade_alert(symbol, curr_close, direction, bid, ask)

        except Exception as e:
            print(f"[ERROR] {symbol}: {e}")

# === Run Loop ===
if __name__ == "__main__":
    print("🟢 5-Minute Sniper Bot Running...\n")

    # === OPTIONAL: Test Alert ===
    try:
        send_alert(
            "🔥 <b>#TESTCOIN/USDT (Long📈, x20)</b> 🔥\n"
            "💰 <b>Entry</b> - 0.1234\n"
            "🎯 <b>Take-Profit:</b>\n"
            "🥉 TP1 (40%) - 0.1258\n"
            "🥈 TP2 (60%) - 0.1270\n"
            "🥇 TP3 (80%) - 0.1300\n"
            "🚀 TP4 (100%) - 0.1350"
        )
        print("[TEST ALERT] Sent successfully.")
    except Exception as e:
        print(f"[TEST ALERT ERROR] {e}")

    while True:
        check_market()
        time.sleep(CHECK_INTERVAL)



