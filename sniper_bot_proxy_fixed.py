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
PROXY = "http://proxy.scrapeops.io:5353"

TP_MULTIPLIERS = [1.02, 1.04, 1.06, 1.08]
BREAKOUT_THRESHOLD = 1.012

client = httpx.AsyncClient(proxies=PROXY, timeout=15.0)
bot = Bot(token=TELEGRAM_BOT_TOKEN)

def get_bybit_client():
    return HTTP(api_key=API_KEY, api_secret=API_SECRET, testnet=False)

async def get_perp_symbols(bybit_client):
    try:
        resp = bybit_client.get_tickers(category="linear")
        return [s["symbol"] for s in resp["result"]["list"] if "USDT" in s["symbol"]]
    except Exception as e:
        print(f"Error fetching symbols: {e}")
        return []

async def get_kline(symbol):
    try:
        url = f"https://api.bybit.com/v5/market/kline"
        params = {"category": "linear", "symbol": symbol, "interval": "1", "limit": 5}
        resp = await client.get(url, params=params)
        return resp.json()
    except Exception as e:
        print(f"Kline fetch failed: {e}")
        return {}

async def scan_market():
    bybit_client = get_bybit_client()
    symbols = await get_perp_symbols(bybit_client)

    for symbol in symbols:
        kline_data = await get_kline(symbol)
        if not kline_data or "result" not in kline_data:
            continue

        candles = kline_data["result"]["list"]
        if len(candles) < 2:
            continue

        prev = candles[-2]
        latest = candles[-1]

        prev_close = float(prev[4])
        curr_close = float(latest[4])
        volume = float(latest[5])
        timestamp = int(latest[0])

        if curr_close > prev_close * BREAKOUT_THRESHOLD:
            await send_alert(symbol, curr_close, volume, "Long📈")

async def send_alert(symbol, price, volume, direction):
    msg = (
        f"🔥 #{symbol} ( {direction}, x20 ) 🔥\n"
        f"Entry - {price:.4f}\n"
        f"Take-Profit:\n"

