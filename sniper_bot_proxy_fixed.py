import asyncio
import httpx
import time
from datetime import datetime
import pandas as pd
from pybit.unified_trading import HTTP
from telegram import Bot

# --- USER CONFIG ---
TELEGRAM_BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
TELEGRAM_CHANNEL_ID = "-1002674839519"
API_KEY = "your_bybit_readonly_key"
API_SECRET = "your_bybit_readonly_secret"

TP_MULTIPLIERS = [1.02, 1.04, 1.06, 1.08]
BREAKOUT_THRESHOLD = 1.012
CHECK_INTERVAL = 60  # seconds

bot = Bot(token=TELEGRAM_BOT_TOKEN)

def get_client():
    return HTTP(
        api_key=API_KEY,
        api_secret=API_SECRET,
        testnet=False
    )

client = get_client()

def format_alert(symbol, entry_price, direction):
    dir_label = "Long📈" if direction == "long" else "Short📉"
    tps = [round(entry_price * tp, 5) if direction == "long" else round(entry_price / tp, 5) for tp in TP_MULTIPLIERS]
    tp_msg = "\n".join([
        f"🥉 TP1: {tps[0]}\n🥈 TP2: {tps[1]}\n🥇 TP3: {tps[2]}\n🚀 TP4: {tps[3]}"
    ])
    return f"🔥 #{symbol}/USDT ({dir_label}, x20) 🔥\nEntry - {entry_price}\nTake-Profit:\n{tp_msg}"

async def check_market():
    while True:
        try:
            tickers = client.get_tickers(category="linear")["result"]["list"]
            for ticker in tickers:
                symbol = ticker["symbol"]
                if "USDT" not in symbol:
                    continue
                price_change = float(ticker["price24hPcnt"])
                last_price = float(ticker["lastPrice"])
                if price_change >= (BREAKOUT_THRESHOLD - 1):
                    alert = format_alert(symbol, last_price, "long")
                    bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=alert)
                elif price_change <= -(BREAKOUT_THRESHOLD - 1):
                    alert = format_alert(symbol, last_price, "short")
                    bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=alert)
        except Exception as e:
            print(f"Error: {e}")
        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(check_market())

