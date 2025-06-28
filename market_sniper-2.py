import requests
import time
from telegram import Bot

# --- CONFIGURATION ---
BOT_TOKEN = "6441443037:AAGZrcM0P7PXw7ox5nEkHvvRD5p1kXYSwJc"
CHANNEL_ID = "@chatxbot6363"
bot = Bot(token=BOT_TOKEN)

SYMBOLS_URL = "https://api.bybit.com/v5/market/tickers?category=linear"
KLINE_URL = "https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}&interval=5&limit=2"
DEPTH_URL = "https://api.bybit.com/v5/market/orderbook?category=linear&symbol={symbol}"
CHECK_INTERVAL = 300  # 5 minutes
PUMP_THRESHOLD = 1.5  # % move per 5 min candle
DUMP_THRESHOLD = -1.5
DEPTH_LEVEL = 25
IMBALANCE_THRESHOLD = 1.5

def get_depth(symbol):
    try:
        r = requests.get(DEPTH_URL.format(symbol=symbol), timeout=5)
        data = r.json()
        asks = data["result"]["asks"][:DEPTH_LEVEL]
        bids = data["result"]["bids"][:DEPTH_LEVEL]
        total_ask = sum(float(x[1]) for x in asks)
        total_bid = sum(float(x[1]) for x in bids)
        return total_bid, total_ask
    except:
        return None, None

def send_alert(symbol, price, move_type, bid=None, ask=None):
    emoji = "📈" if move_type == "pump" else "📉"
    fire = "🔥"
    liquidity_msg = ""
    if bid and ask:
        ratio = bid / ask if ask != 0 else 0
        if ratio > IMBALANCE_THRESHOLD:
            liquidity_msg = f"🟢 Buy Wall Detected (B/A ratio: {ratio:.1f})"
        elif ratio < 1 / IMBALANCE_THRESHOLD:
            liquidity_msg = f"🔴 Sell Wall Detected (B/A ratio: {ratio:.1f})"

    message = (
        f"{fire} #{symbol}/USDT ({'Long📈' if move_type == 'pump' else 'Short📉'}, x20) {fire}\n"
        f"Entry - {price}\n"
        "Take-Profit:\n"
        "🥉 TP1 (40%)\n"
        "🥈 TP2 (60%)\n"
        "🥇 TP3 (80%)\n"
        "🚀 TP4 (100%)\n"
        f"{liquidity_msg}"
    )
    bot.send_message(chat_id=CHANNEL_ID, text=message)

def check_market():
    try:
        response = requests.get(SYMBOLS_URL, timeout=10)
        data = response.json()

        for item in data["result"]["list"]:
            symbol = item["symbol"]
            if not symbol.endswith("USDT"):
                continue

            kline_resp = requests.get(KLINE_URL.format(symbol=symbol), timeout=5)
            kline_data = kline_resp.json()
            if "result" not in kline_data or not kline_data["result"]["list"]:
                continue

            klines = kline_data["result"]["list"]
            prev_close = float(klines[-2][4])
            curr_close = float(klines[-1][4])

            change = ((curr_close - prev_close) / prev_close) * 100

            if abs(change) >= PUMP_THRESHOLD:
                bid, ask = get_depth(symbol)
                move = "pump" if change > 0 else "dump"
                send_alert(symbol, curr_close, move, bid, ask)

    except Exception as e:
        print(f"[ERROR] {e}")

# --- MAIN LOOP ---
if __name__ == "__main__":
    print("🔁 5-Minute Sniper Bot Running...")
    while True:
        check_market()
        time.sleep(CHECK_INTERVAL)
