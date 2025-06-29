
import asyncio
import httpx
import time
import json
from datetime import datetime, timedelta
from telegram import Bot

BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
CHANNEL_ID = "-1002674839519"
INTERVAL = "5"
BYBIT_URL = "https://api.bybit.com"
HEADERS = {"Accept": "application/json"}

bot = Bot(token=BOT_TOKEN)

def format_signal(symbol, entry, tp1, tp2, tp3, tp4):
    return f'''
🔥 #{symbol}/USDT (Long📈, x20) 🔥
Entry - {entry}
Take-Profit:
🥉 TP1 - {tp1}
🥈 TP2 - {tp2}
🥇 TP3 - {tp3}
🚀 TP4 - {tp4}
'''

async def send_telegram_message(message):
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=message)
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

async def fetch_perps():
    async with httpx.AsyncClient() as client:
        url = f"{BYBIT_URL}/v5/market/instruments-info?category=linear"
        try:
            resp = await client.get(url, headers=HEADERS, timeout=10)
            data = resp.json()
            return [d["symbol"] for d in data["result"]["list"] if "USDT" in d["symbol"]]
        except Exception as e:
            print(f"Error fetching perpetuals: {e}")
            return []

async def fetch_klines(symbol):
    end = int(time.time() * 1000)
    start = end - (300 * 1000 * 5)  # last 5 candles of 5-min intervals
    url = f"{BYBIT_URL}/v5/market/kline?category=linear&symbol={symbol}&interval={INTERVAL}&start={start}&end={end}&limit=5"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=HEADERS, timeout=10)
            data = resp.json()
            return data["result"]["list"]
        except:
            return []

def detect_breakout(klines):
    if len(klines) < 5:
        return False, None
    *_, c4, c5 = klines[-5:]
    c4_close, c5_close = float(c4[4]), float(c5[4])
    c4_vol, c5_vol = float(c4[5]), float(c5[5])
    if c5_close > c4_close * 1.01 and c5_vol > c4_vol * 1.5:
        return True, c5_close
    return False, None

async def scan_market():
    symbols = await fetch_perps()
    print(f"Scanning {len(symbols)} markets...")
    for symbol in symbols:
        klines = await fetch_klines(symbol)
        breakout, entry = detect_breakout(klines)
        if breakout:
            tp1 = round(entry * 1.01, 4)
            tp2 = round(entry * 1.015, 4)
            tp3 = round(entry * 1.02, 4)
            tp4 = round(entry * 1.025, 4)
            msg = format_signal(symbol, entry, tp1, tp2, tp3, tp4)
            await send_telegram_message(msg)
            print(f"Signal sent for {symbol}")

async def main_loop():
    await send_telegram_message("✅ [TEST ALERT] Market Sniper Bot is live (using proxy)")
    while True:
        await scan_market()
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main_loop())

