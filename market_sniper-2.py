
import time
import requests
import json

# === CONFIG ===
BOT_TOKEN = "8029194291:AAHJDbsInstarivWEMPBkxsHFfH4zFCvDt8"
CHAT_ID = "7186880587"  # Sending directly to user's private chat ID
CHECK_INTERVAL = 300  # 5-minute candles
PUMP_THRESHOLD = 0.015  # 1.5% price move triggers signal

# === PROXY WRAPPER FOR BYBIT ===
PROXY_URL = "https://api.proxycurl.com/proxy"

def proxy_get(url, params=None):
    try:
        full_url = f"{PROXY_URL}?url={url}"
        response = requests.get(full_url, params=params)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"[ERROR - Proxy GET] {e}")
        return None

# === ALERT SENDER ===
def send_alert(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        r = requests.post(url, data=payload)
        print(f"[INFO:Sent alert: {message}] | Status: {r.status_code}")
    except Exception as e:
        print(f"[ERROR - Send alert] {e}")

# === GET SYMBOL LIST ===
def get_symbols():
    url = "https://api.bybit.com/v5/market/tickers?category=linear"
    data = proxy_get(url)
    if not data or "result" not in data:
        return []
    return [item["symbol"] for item in data["result"]["list"] if item["symbol"].endswith("USDT")]

# === GET PRICE ===
def get_price(symbol):
    url = f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={symbol}"
    data = proxy_get(url)
    if not data or "result" not in data:
        return None
    return float(data["result"]["list"][0]["lastPrice"])

# === GET DEPTH ===
def get_depth(symbol):
    url = f"https://api.bybit.com/v5/market/orderbook?category=linear&symbol={symbol}"
    data = proxy_get(url)
    if not data or "result" not in data:
        return None, None
    bid = float(data["result"]["b"][0][0])
    ask = float(data["result"]["a"][0][0])
    return bid, ask

# === MAIN CHECK ===
previous_prices = {}

def check_market():
    global previous_prices
    symbols = get_symbols()
    for symbol in symbols:
        try:
            curr_price = get_price(symbol)
            if not curr_price:
                continue

            prev_price = previous_prices.get(symbol, curr_price)
            change = (curr_price - prev_price) / prev_price

            if abs(change) >= PUMP_THRESHOLD:
                bid, ask = get_depth(symbol)
                move = "📈 pump" if change > 0 else "📉 dump"
                send_alert(
                    f"🔥 #{symbol} (Long📈, x20) 🔥\n"
                    f"Entry - {curr_price:.4f}\n"
                    f"Take-Profit:\n"
                    f"🥉 TP1 (40%) = {curr_price * 1.015:.4f}\n"
                    f"🥈 TP2 (60%) = {curr_price * 1.025:.4f}\n"
                    f"🥇 TP3 (80%) = {curr_price * 1.035:.4f}\n"
                    f"🚀 TP4 (100%) = {curr_price * 1.045:.4f}"
                )

            previous_prices[symbol] = curr_price

        except Exception as e:
            print(f"[ERROR - check_market for {symbol}] {e}")

# === MAIN LOOP ===
if __name__ == "__main__":
    print("🤖 5-Minute Sniper Bot Running...")

    # Send test alert on startup
    try:
        send_alert(
            "🔥 #TESTCOIN/USDT (Long📈, x20) 🔥\n"
            "Entry - 0.1234\n"
            "Take-Profit:\n"
            "🥉 TP1 (40%) = 0.1258\n"
            "🥈 TP2 (60%) = 0.1270\n"
            "🥇 TP3 (80%) = 0.1300\n"
            "🚀 TP4 (100%) = 0.1350"
        )
        print("[TEST ALERT] Sent.")
    except Exception as e:
        print(f"[TEST ALERT ERROR] {e}")

    while True:
        check_market()
        time.sleep(CHECK_INTERVAL)



