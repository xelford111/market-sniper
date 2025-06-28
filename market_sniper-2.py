import requests
import time
from telegram import Bot

# --- CONFIGURATION ---
BOT_TOKEN = "6441443037:AAGZrcM0P7PXw7ox5nEkHvvRD5p1kXYSwJc"
CHANNEL_ID = "@chatxbot6363"
bot = Bot(token=BOT_TOKEN)

TICKER_URL = "https://api.bybit.com/v5/market/tickers?category=linear"
DEPTH_URL = "https://api.bybit.com/v5/market/orderbook?category=linear&symbol={symbol}"
CHECK_INTERVAL = 60
PUMP_THRESHOLD = 2.0
DUMP_THRESHOLD = -2.0
DEPTH_LEVEL = 25
IMBALANCE_THRESHOLD = 1.5  # Ratio of buy/sell volume to trigger alert

last_prices = {}

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
        response = requests.get(TICKER_URL, timeout=10)
        data = response.json()

        for item in data["result"]["list"]:
            symbol = item["symbol"]
            if not symbol.endswith("USDT"):
                continue

            last_price = float(item["lastPrice"])
            prev_price = last_prices.get(symbol)

            if prev_price:
                price_change = ((last_price - prev_price) / prev_price) * 100
                if abs(price_change) >= PUMP_THRESHOLD:
                    bid, ask = get_depth(symbol)
                    move = "pump" if price_change > 0 else "dump"
                    send_alert(symbol, last_price, move, bid, ask)

            last_prices[symbol] = last_price

    except Exception as e:
        print(f"[ERROR] {e}")

# --- MAIN LOOP ---
if __name__ == "__main__":
    print("🧠 Enhanced Sniper Bot w/ Liquidity Running...")
    while True:
        check_market()
        time.sleep(CHECK_INTERVAL)
