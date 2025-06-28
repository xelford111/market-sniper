
import requests
import time
from telegram import Bot, request

# === CONFIGURATION ===
BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
CHANNEL_ID = "-1002674839519"  # Your Telegram channel
PROXY_URL = "http://proxy.scrapeops.io:8001"  # Free working proxy for test use

# === BOT SETUP WITH PROXY ===
req = request.Request(proxy_url=PROXY_URL)
bot = Bot(token=BOT_TOKEN, request=req)

def send_alert(symbol, direction, leverage, entry_price):
    message = f"""🔥 #{symbol}/USDT ({direction}, x{leverage}) 🔥
Entry - {entry_price}
Take-Profit:
🥉 TP1 (40% of profit)
🥈 TP2 (60% of profit)
🥇 TP3 (80% of profit)
🚀 TP4 (100% of profit)"""
    bot.send_message(chat_id=CHANNEL_ID, text=message)

def get_bybit_data():
    url = "https://api.bybit.com/v5/market/tickers?category=linear"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        return data["result"]["list"]
    except Exception as e:
        print("❌ Bybit fetch failed:", e)
        return []

def detect_signals(data):
    for item in data:
        symbol = item["symbol"]
        last_price = float(item["lastPrice"])
        vol = float(item["turnover24h"])
        pct_change = float(item["price24hPcnt"]) * 100

        if vol > 1_000_000 and abs(pct_change) > 4:
            direction = "Long📈" if pct_change > 0 else "Short📉"
            send_alert(symbol, direction, 20, last_price)

# === STARTUP MESSAGE ===
print("✅ Market Sniper Bot (with Proxy) running...")
bot.send_message(chat_id=CHANNEL_ID, text="🚨 [TEST] Market Sniper Bot is live with proxy!")

# === LOOP ===
while True:
    tickers = get_bybit_data()
    detect_signals(tickers)
    time.sleep(60)
