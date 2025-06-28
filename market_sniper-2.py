
import asyncio
import aiohttp
from telegram import Bot
from datetime import datetime
import logging
import os

# === CONFIG ===
BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
CHANNEL_ID = "-1002674839519"
PROXY_URL = "http://149.129.213.66:3128"
BYBIT_TICKER_URL = "https://api.bybit.com/v5/market/tickers?category=linear"

# === INIT BOT WITH PROXY ===
bot = Bot(token=BOT_TOKEN, request=aiohttp.request("GET", proxy=PROXY_URL))

async def fetch_bybit_data():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(BYBIT_TICKER_URL, proxy=PROXY_URL) as response:
                data = await response.json()
                return data.get("result", {}).get("list", [])
    except Exception as e:
        logging.error(f"[ERROR] Failed to fetch from Bybit: {e}")
        return []

async def scan_market():
    await bot.send_message(chat_id=CHANNEL_ID, text="🚀 [TEST ALERT] Market Sniper Bot is live!")
    while True:
        coins = await fetch_bybit_data()
        for coin in coins:
            symbol = coin["symbol"]
            last_price = float(coin["lastPrice"])
            prev_price = float(coin.get("prevPrice24h", 0)) or last_price
            pct_change = ((last_price - prev_price) / prev_price) * 100 if prev_price != 0 else 0
            volume_usd = float(coin["turnover24h"])

            if abs(pct_change) >= 5 and volume_usd > 1000000:
                direction = "Long📈" if pct_change > 0 else "Short📉"
                leverage = "x20"
                msg = f"🔥 {symbol}/USDT ({direction}, {leverage}) 🔥\nEntry - {last_price}\nTake-Profit:\n🥉 TP1\n🥈 TP2\n🥇 TP3\n🚀 TP4"
                await bot.send_message(chat_id=CHANNEL_ID, text=msg)

        await asyncio.sleep(60)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(scan_market())
