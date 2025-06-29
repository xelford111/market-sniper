
import asyncio
import time
import httpx
import json
import hmac
import hashlib
from datetime import datetime
from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest

# === CONFIG ===
TELEGRAM_BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
TELEGRAM_CHAT_ID = "-1002674839519"
BYBIT_API_URL = "https://api.bybit.com"
CANDLE_INTERVAL = "5"  # 5-minute candles
VOLUME_SPIKE_MULTIPLIER = 2.0
PRICE_MOVE_THRESHOLD = 1.5  # percent
TOP_PAIRS_LIMIT = 30
PROXY_ENABLED = True
PROXY_URL = "http://proxy.example.com:8080"

# === TELEGRAM ALERT ===
def send_telegram_alert(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = httpx.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")

# === FETCH COIN LIST ===
async def get_perpetual_symbols():
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BYBIT_API_URL}/v5/market/instruments-info?category=linear")
        data = r.json()
        return [x["symbol"] for x in data["result"]["list"] if "USDT" in x["symbol"]]

# === FETCH LATEST CANDLES ===
async def get_kline(symbol):
    url = f"{BYBIT_API_URL}/v5/market/kline"
    params = {"category": "linear", "symbol": symbol, "interval": CANDLE_INTERVAL, "limit": 3}
    async with httpx.AsyncClient() as client:
        r = await client.get(url, params=params)
        return r.json()["result"]["list"]

# === SPOOFING CHECK ===
async def detect_spoofing(symbol):
    url = f"{BYBIT_API_URL}/v5/market/orderbook"
    params = {"category": "linear", "symbol": symbol, "limit": 50}
    async with httpx.AsyncClient() as client:
        r = await client.get(url, params=params)
        ob = r.json()["result"]
        bids = ob["b"]
        asks = ob["a"]
        total_bid = sum(float(b[1]) for b in bids)
        total_ask = sum(float(a[1]) for a in asks)
        ratio = total_bid / total_ask if total_ask else 0
        return ratio > 2.5 or ratio < 0.4  # spoofing threshold

# === MAIN SNIPING LOOP ===
async def market_sniper():
    symbols = await get_perpetual_symbols()
    for symbol in symbols[:TOP_PAIRS_LIMIT]:
        try:
            klines = await get_kline(symbol)
            if len(klines) < 3:
                continue
            _, _, high1, low1, close1, vol1 = map(float, klines[-3])
            _, _, high2, low2, close2, vol2 = map(float, klines[-2])
            _, _, high3, low3, close3, vol3 = map(float, klines[-1])

            price_move = (close3 - close2) / close2 * 100
            volume_spike = vol3 > VOLUME_SPIKE_MULTIPLIER * max(vol1, vol2)

            if abs(price_move) >= PRICE_MOVE_THRESHOLD and volume_spike:
                spoofing = await detect_spoofing(symbol)
                alert = f"🔥 #{symbol}/USDT {'Long📈' if price_move > 0 else 'Short📉'} 🔥\n"
                alert += f"<b>Entry</b>: {close3:.4f}\n"
                alert += f"TP1: {close3 * 1.01:.4f} | TP2: {close3 * 1.02:.4f} | TP3: {close3 * 1.03:.4f}\n"
                if spoofing:
                    alert += "⚠️ <i>Spoofing Detected</i>"

                send_telegram_alert(alert)
        except Exception as e:
            print(f"[ERROR] {symbol}: {e}")

# === START ===
if __name__ == "__main__":
    send_telegram_alert("✅ [TEST ALERT] Market Sniper Bot is live (5m candles, proxy enabled)")
    asyncio.run(market_sniper())
