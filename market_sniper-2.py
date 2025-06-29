
import asyncio
import logging
import time
import pandas as pd
from pybit.unified_trading import HTTP
from datetime import datetime, timedelta
import httpx
import requests

# Telegram setup
TELEGRAM_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
CHANNEL_ID = "-1002674839519"

# Constants
INTERVAL = 5  # minutes
LIMIT = 100
VOLUME_THRESHOLD = 2.0  # 2x spike
WHALE_THRESHOLD = 100000  # $ value
ORDERBOOK_DEPTH = 50

session = HTTP(testnet=False)

def send_telegram_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHANNEL_ID, "text": text}
    try:
        r = requests.post(url, data=data)
        if not r.ok:
            print(f"Telegram error: {r.text}")
    except Exception as e:
        print(f"Telegram send error: {e}")

async def fetch_candles(symbol):
    try:
        res = session.get_kline(category="linear", symbol=symbol, interval=str(INTERVAL), limit=LIMIT)
        return res["result"]["list"]
    except Exception as e:
        print(f"Error fetching candles for {symbol}: {e}")
        return []

async def fetch_orderbook(symbol):
    try:
        url = f"https://api.bybit.com/v5/market/orderbook?category=linear&symbol={symbol}"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            data = response.json()
            return data["result"]
    except Exception as e:
        print(f"Orderbook fetch failed: {e}")
        return {}

def detect_volume_spike(df):
    if len(df) < 2:
        return False
    prev_vol = float(df[-2][5])
    curr_vol = float(df[-1][5])
    return curr_vol > prev_vol * VOLUME_THRESHOLD

def detect_whale_order(orderbook):
    try:
        bids = orderbook["b"]
        asks = orderbook["a"]
        top_bid = float(bids[0][1])
        top_ask = float(asks[0][1])
        return top_bid > WHALE_THRESHOLD or top_ask > WHALE_THRESHOLD
    except Exception:
        return False

def detect_spoofing(orderbook):
    try:
        bids = orderbook["b"][:ORDERBOOK_DEPTH]
        asks = orderbook["a"][:ORDERBOOK_DEPTH]
        bid_volume = sum(float(b[1]) for b in bids)
        ask_volume = sum(float(a[1]) for a in asks)
        imbalance = abs(bid_volume - ask_volume) / max(bid_volume, ask_volume)
        return imbalance > 0.7
    except Exception:
        return False

async def analyze_symbol(symbol):
    candles = await fetch_candles(symbol)
    orderbook = await fetch_orderbook(symbol)
    if not candles or not orderbook:
        return

    volume_spike = detect_volume_spike(candles)
    whale_alert = detect_whale_order(orderbook)
    spoofing = detect_spoofing(orderbook)

    if volume_spike or whale_alert or spoofing:
        msg = f"🔥 #{symbol}/USDT Detected!"
        if volume_spike:
            msg += "
📊 Volume Spike"
        if whale_alert:
            msg += "
🐋 Whale Order Detected"
        if spoofing:
            msg += "
🧙‍♂️ Potential Spoofing"
        send_telegram_message(msg)

async def main_loop():
    send_telegram_message("✅ [TEST ALERT] Market Sniper Bot is live (via proxy)")
    market_data = session.get_instruments_info(category="linear")
    symbols = [item["symbol"] for item in market_data["result"]["list"] if "USDT" in item["symbol"]]

    while True:
        tasks = [analyze_symbol(symbol) for symbol in symbols]
        await asyncio.gather(*tasks)
        time.sleep(INTERVAL * 60)

if __name__ == "__main__":
    asyncio.run(main_loop())
