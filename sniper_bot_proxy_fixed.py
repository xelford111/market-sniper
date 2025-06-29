import asyncio
import httpx
import time
from datetime import datetime
from pybit.unified_trading import HTTP
from telegram import Bot

# === YOUR CONFIG ===
API_KEY = "your_bybit_readonly_key"
API_SECRET = "your_bybit_readonly_secret"
TELEGRAM_BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
TELEGRAM_CHANNEL_ID = "-1002674839519"
PROXY_URL = "http://proxy.scrapeops.io:5353"

TP_MULTIPLIERS = [1.02, 1.04, 1.06, 1.08]
BREAKOUT_THRESHOLD = 1.012
SIGNAL_SCORE_THRESHOLD = 3.0

# === SETUP CLIENT WITH FORCED PROXY ===
def get_client():
    transport = httpx.AsyncHTTPTransport(proxy=PROXY_URL)
    http_client = httpx.AsyncClient(transport=transport)
    return HTTP(api_key=API_KEY, api_secret=API_SECRET, testnet=False, http_client=http_client)

client = get_client()
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# === SCAN MARKET ===
async def scan_market():
    try:
        tickers = (await client.get_tickers(category="linear"))["result"]["list"]
    except Exception as e:
        print(f"[ERROR] Ticker fetch failed: {e}")
        return

    for s in tickers:
        symbol = s["symbol"]
        if "USDT" not in symbol:
            continue
        try:
            mark_price = float(s["lastPrice"])
            vol = float(s["turnover24h"])
            open_price = float(s["indexPrice"])
            score = 0

            # Price breakout
            if mark_price > open_price * BREAKOUT_THRESHOLD:
                score += 1

            # Volume filter
            if vol > 10000000:
                score += 1

            # Add spoofing / wall detection logic here if needed

            # Signal strength
            if score >= SIGNAL_SCORE_THRESHOLD:
                await send_signal(symbol, mark_price)
        except Exception as e:
            print(f"[ERROR] While scanning {symbol}: {e}")

# === SEND ALERT ===
async def send_signal(symbol, entry):
    tps = [round(entry * m, 6) for m in TP_MULTIPLIERS]
    message = f"""🔥 #{symbol} (Long📈, x20) 🔥
Entry - {entry}
Take-Profit:
🥉 TP1 {tps[0]}
🥈 TP2 {tps[1]}
🥇 TP3 {tps[2]}
🚀 TP4 {tps[3]}"""
    try:
        await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=message)
        print(f"[SENT] {symbol} breakout alert")
    except Exception as e:
        print(f"[ERROR] Sending alert: {e}")

# === MAIN LOOP ===
async def main_loop():
    while True:
        await scan_market()
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main_loop())

