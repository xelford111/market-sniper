import asyncio
import httpx
import time
from datetime import datetime
import pandas as pd
from pybit.unified_trading import HTTP
from telegram import Bot

# === USER CONFIG (LIVE) ===
API_KEY = "wL5s9Thvmz4wiOFtQh"
API_SECRET = "fOW8R0SgOqXfB7bO3OxpYvR3bJPI2IuXuxiN"
TELEGRAM_BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
TELEGRAM_CHANNEL_ID = "-1002674839519"
PROXY = "http://proxy.scrapeops.io:5353"

TP_MULTIPLIERS = [1.02, 1.04, 1.06, 1.08]
BREAKOUT_THRESHOLD = 1.012  # Loosened for more signal sensitivity

bot = Bot(token=TELEGRAM_BOT_TOKEN)

def get_client():
    transport = httpx.AsyncHTTPTransport(proxy=PROXY)
    http_client = httpx.AsyncClient(transport=transport, timeout=15.0)
    return HTTP(api_key=API_KEY, api_secret=API_SECRET, testnet=False, httpx_client=http_client)

def format_alert(symbol, side, entry_price):
    direction = "Long📈" if side == "Buy" else "Short📉"
    tps = [round(entry_price * m, 4) if side == "Buy" else round(entry_price / m, 4) for m in TP_MULTIPLIERS]
    tp_lines = "\n".join([
        f"🥉 TP1 ({TP_MULTIPLIERS[0]-1:.0%}) - {tps[0]}",
        f"🥈 TP2 ({TP_MULTIPLIERS[1]-1:.0%}) - {tps[1]}",
        f"🥇 TP3 ({TP_MULTIPLIERS[2]-1:.0%}) - {tps[2]}",
        f"🚀 TP4 ({TP_MULTIPLIERS[3]-1:.0%}) - {tps[3]}"
    ])
    return f"""🔥 #{symbol}USDT ({direction}, x20) 🔥
Entry - {entry_price}

Take-Profit:
{tp_lines}"""

async def scan_market():
    client = get_client()
    try:
        tickers = await client.get_tickers(category="linear")
        usdt_pairs = [t['symbol'] for t in tickers['result']['list'] if "USDT" in t['symbol']]
    except Exception as e:
        print(f"Ticker fetch error: {e}")
        return

    for symbol in usdt_pairs:
        try:
            kline = await client.get_kline(category="linear", symbol=symbol, interval=1)
            candles = kline['result']['list']
            if len(candles) < 2:
                continue

            prev_close = float(candles[-2][4])
            last_close = float(candles[-1][4])
            volume = float(candles[-1][5])

            if last_close > prev_close * BREAKOUT_THRESHOLD:
                msg = format_alert(symbol, "Buy", last_close)
                await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=msg)
                print(f"Long breakout: {symbol}")

            elif last_close < prev_close / BREAKOUT_THRESHOLD:
                msg = format_alert(symbol, "Sell", last_close)
                await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=msg)
                print(f"Short breakout: {symbol}")

        except Exception as e:
            print(f"{symbol} error: {e}")

async def run_forever():
    while True:
        await scan_market()
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(run_forever())


