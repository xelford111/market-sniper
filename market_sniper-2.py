
import requests
import time
from telegram import Bot
from telegram.utils.request import Request

# === Configuration ===
BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
CHANNEL_ID = "-1002674839519"
PROXY_URL = "http://149.129.213.66:3128"  # Working free proxy
BYBIT_URL = "https://api.bybit.com/v5/market/tickers?category=linear"

# === Telegram Bot Setup with Proxy ===
request = Request(proxy_url=PROXY_URL)
bot = Bot(token=BOT_TOKEN, request=request)

# === Send formatted signal to Telegram ===
def send_signal(symbol, direction, price):
    message = f"""🔥 #{symbol}/USDT ({direction}, x20) 🔥
Entry - {price}
Take-Profit:
🥉 TP1 (40% of profit)
🥈 TP2 (60% of profit)
🥇 TP3 (80% of profit)
🚀 TP4 (100% of profit)"""
    bot.send_message(chat_id=CHANNEL_ID, text=message)

# === Fetch and filter Bybit market data ===
def get_signals():
    try:
        res = requests.get(BYBIT_URL, timeout=10)
        data = res.json()["result"]["list"]
        for item in data:
            symbol = item["symbol"]
            last_price = float(item["lastPrice"])
            pct = float(item["price24hPcnt"]) * 100
            vol = float(item["turnover24h"])

            if vol > 1_000_000 and abs(pct) > 4:
                direction = "Long📈" if pct > 0 else "Short📉"
                send_signal(symbol, direction, last_price)

    except Exception as e:
        print("[ERROR]", e)

# === Test alert on start ===
bot.send_message(chat_id=CHANNEL_ID, text="🚨 [TEST] Sniper bot is now running with proxy!")

# === Continuous Monitoring ===
print("✅ Sniper bot running...")
while True:
    get_signals()
    time.sleep(60)

