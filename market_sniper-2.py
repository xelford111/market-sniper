import asyncio
import aiohttp
import json
import time
import math
from telegram import Bot

# === CONFIGURATION ===
BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
CHAT_ID = "-1002674839519"  # Telegram Channel ID for @chatxbot6363
BYBIT_URL = "https://api.bybit.com/v5/market/tickers?category=linear"
PROXY = "http://quickproxy.io:8080"  # Example proxy URL
LEVERAGE = 20

bot = Bot(token=BOT_TOKEN, request_kwargs={"proxy_url": PROXY})

# === FORMATTING ===
def format_signal(symbol, direction, entry):
    return f"""
🔥 #{symbol}/USDT ({direction}📈, x{LEVERAGE}) 🔥
Entry - {entry}
Take-Profit:
🥉 TP1 (40% of profit)
🥈 TP2 (60% of profit)
🥇 TP3 (80% of profit)
🚀 TP4 (100% of profit)
"""

# === SIGNAL CONDITIONS ===
def detect_signal(ticker):
    try:
        symbol = ticker['symbol']
        if not symbol.endswith("USDT"):
            return None

        last_price = float(ticker['lastPrice'])
        volume = float(ticker['turnover24h'])
        price_change = float(ticker['price24hPcnt'])

        if volume > 5000000 and abs(price_change) > 0.04:
            direction = "Long" if price_change > 0 else "Short"
            return format_signal(symbol, direction, last_price)

    except:
        return None
    return None

# === MAIN LOOP ===
async def main():
    await bot.send_message(chat_id=CHAT_ID, text="🟢 [TEST ALERT] Market Sniper Bot is live (proxy enabled)")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(BYBIT_URL, proxy=PROXY) as resp:
                    data = await resp.json()
                    if 'result' in data and 'list' in data['result']:
                        for ticker in data['result']['list']:
                            signal = detect_signal(ticker)
                            if signal:
                                await bot.send_message(chat_id=CHAT_ID, text=signal)

            except Exception as e:
                print("ERROR:", e)

            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())

