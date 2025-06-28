import time
import requests
from telegram import Bot

# === CONFIGURATION ===
TELEGRAM_BOT_TOKEN = "6441443037:AAGZrcM0P7PXw7ox5nEkHvvRD5p1kXYSwJc"
TELEGRAM_CHAT_ID = "@chatxbot6363"
CHECK_INTERVAL = 300  # 5 minutes
PUMP_THRESHOLD = 1.5  # % change to trigger signal

bot = Bot(token=TELEGRAM_BOT_TOKEN)

def send_alert(message):
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)

def get_depth(symbol):
    url = f"https://api.bybit.com/v2/public/orderBook/L2?symbol={symbol}"
    response = requests.get(url)
    data = response.json()
    bids = [i for i in data['result'] if i['side'] == 'Buy']
    asks = [i for i in data['result'] if i['side'] == 'Sell']
    top_bid = float(bids[0]['price']) if bids else 0
    top_ask = float(asks[0]['price']) if asks else 0
    return top_bid, top_ask

def get_klines(symbol):
    url = f"https://api.bybit.com/public/linear/kline?symbol={symbol}&interval=5&limit=2"
    response = requests.get(url)
    return response.json().get("result", [])

def check_market():
    try:
        symbols = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT"]
        for symbol in symbols:
            klines = get_klines(symbol)
            if len(klines) < 2:
                continue
            prev_close = float(klines[-2]["close"])
            curr_close = float(klines[-1]["close"])
            change = ((curr_close - prev_close) / prev_close) * 100
            if abs(change) >= PUMP_THRESHOLD:
                bid, ask = get_depth(symbol)
                move = "pump" if change > 0 else "dump"
                send_alert(f"🔥 #{symbol}/USDT ({'Long📈' if move == 'pump' else 'Short📉'}, x20) 🔥\n"
                           f"Entry - {curr_close}\n"
                           f"Take-Profit:\n"
                           f"🥉 TP1 (40%) - {curr_close * 1.01:.4f}\n"
                           f"🥈 TP2 (60%) - {curr_close * 1.015:.4f}\n"
                           f"🥇 TP3 (80%) - {curr_close * 1.02:.4f}\n"
                           f"🚀 TP4 (100%) - {curr_close * 1.03:.4f}")
    except Exception as e:
        print(f"[ERROR] {e}")

if __name__ == "__main__":
    print("🧠 5-Minute Sniper Bot Running...")

    # === TEST ALERT BLOCK ===
    try:
        send_alert(
            "🔥 #TESTCOIN/USDT (Long📈, x20) 🔥\n"
            "Entry - 0.1234\n"
            "Take-Profit:\n"
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


