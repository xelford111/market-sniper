import asyncio
import pandas as pd
import httpx
from pybit.unified_trading import HTTP
import logging
import os

TELEGRAM_BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
TELEGRAM_CHAT_ID = "-1002674839519"  # Correct channel ID
BYBIT_API = "https://api.bybit.com"
SYMBOLS_URL = f"{BYBIT_API}/v5/market/instruments-info?category=linear"
CANDLES_URL = f"{BYBIT_API}/v5/market/kline"
ORDERBOOK_URL = f"{BYBIT_API}/v5/market/orderbook"
CHECK_INTERVAL = 300  # every 5 minutes

logging.basicConfig(level=logging.INFO)

async def fetch_symbols(client):
    r = await client.get(SYMBOLS_URL)
    data = r.json()
    return [i["symbol"] for i in data["result"]["list"] if "USDT" in i["symbol"]]

async def fetch_candles(client, symbol):
    r = await client.get(CANDLES_URL, params={
        "category": "linear",
        "symbol": symbol,
        "interval": "5",
        "limit": 5
    })
    return pd.DataFrame(r.json()["result"]["list"], columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"])

async def fetch_orderbook(client, symbol):
    r = await client.get(ORDERBOOK_URL, params={"category": "linear", "symbol": symbol})
    return r.json()["result"]

def detect_spoofing(orderbook):
    top_bids = float(orderbook["b"][0][1])
    top_asks = float(orderbook["a"][0][1])
    imbalance = abs(top_bids - top_asks) / max(top_bids, top_asks)
    return imbalance > 0.6

def detect_whale_activity(orderbook):
    total_bid = sum(float(i[1]) for i in orderbook["b"][:10])
    total_ask = sum(float(i[1]) for i in orderbook["a"][:10])
    return total_bid > 1_000_000 or total_ask > 1_000_000

async def send_telegram_alert(text):
    async with httpx.AsyncClient() as client:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        await client.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text})

async def analyze_symbol(client, symbol):
    candles = await fetch_candles(client, symbol)
    if candles.empty or len(candles) < 3:
        return
    recent = candles.iloc[-1]
    prev = candles.iloc[-2]
    change = (float(recent["close"]) - float(prev["close"])) / float(prev["close"])
    volume_spike = float(recent["volume"]) > float(candles["volume"].astype(float).mean()) * 2
    if abs(change) > 0.02 and volume_spike:
        orderbook = await fetch_orderbook(client, symbol)
        if detect_spoofing(orderbook):
            return await send_telegram_alert(f"🕵️ Spoofing detected on {symbol}")
        if detect_whale_activity(orderbook):
            return await send_telegram_alert(f"🐋 Whale activity on {symbol}")
        direction = "Long📈" if change > 0 else "Short📉"
        entry = float(recent["close"])
        msg = (
            f"🔥 #{symbol} ({direction}, x20) 🔥\n"
            f"Entry - {entry:.4f}\n"
            f"Take-Profit:\n"
            f"🥉 TP1\n"
            f"🥈 TP2\n"
            f"🥇 TP3\n"
            f"🚀 TP4"
        )
        await send_telegram_alert(msg)

async def main_loop():
    transport = httpx.HTTPTransport(retries=2)
    async with httpx.AsyncClient(transport=transport, timeout=10) as client:
        try:
            await send_telegram_alert("✅ [TEST ALERT] Market Sniper Bot is live (using proxy)")
        except Exception as e:
            logging.error(f"❌ Failed to send test alert: {e}")
        while True:
            try:
                symbols = await fetch_symbols(client)
                tasks = [analyze_symbol(client, s) for s in symbols]
                await asyncio.gather(*tasks)
            except Exception as e:
                logging.error(f"Main loop error: {e}")
            await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main_loop())
