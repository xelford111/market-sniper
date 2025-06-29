
import asyncio
import time
import json
import httpx
from datetime import datetime, timedelta

BYBIT_API_URL = "https://api.bybit.com/v5/market/kline"
ORDERBOOK_API = "https://api.bybit.com/v5/market/orderbook"
TELEGRAM_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
TELEGRAM_CHAT_ID = "-1002217394276"  # Your Telegram Channel ID

HEADERS = {"Content-Type": "application/json"}
CANDLE_INTERVAL = "5"  # 5-minute candles
LIMIT = 200
MIN_VOL = 100000  # Adjust this based on market conditions
SIGNIFICANT_WALL_THRESHOLD = 150000  # Size of wall to trigger signal
WHALE_ORDER_SIZE = 80000  # Whale threshold

PROXY = "http://quickproxy.io:8080"

async def send_telegram_alert(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient(proxies=PROXY) as client:
        try:
            await client.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message})
        except Exception as e:
            print("Telegram Error:", e)

async def fetch_all_perp_symbols():
    url = "https://api.bybit.com/v5/market/instruments-info?category=linear"
    async with httpx.AsyncClient(proxies=PROXY) as client:
        r = await client.get(url)
        data = r.json()
        return [s['symbol'] for s in data['result']['list'] if s['symbol'].endswith("USDT")]

async def fetch_kline(symbol):
    url = f"{BYBIT_API_URL}?category=linear&symbol={symbol}&interval={CANDLE_INTERVAL}&limit=2"
    async with httpx.AsyncClient(proxies=PROXY) as client:
        r = await client.get(url)
        candles = r.json()["result"]["list"]
        return candles

async def fetch_orderbook(symbol):
    url = f"{ORDERBOOK_API}?category=linear&symbol={symbol}"
    async with httpx.AsyncClient(proxies=PROXY) as client:
        r = await client.get(url)
        return r.json()["result"]

def detect_spoofing(orderbook):
    bids = orderbook["b"]
    asks = orderbook["a"]
    if float(bids[0][1]) > SIGNIFICANT_WALL_THRESHOLD and float(bids[0][1]) > 1.5 * float(asks[0][1]):
        return "Buy wall spoofing suspected"
    if float(asks[0][1]) > SIGNIFICANT_WALL_THRESHOLD and float(asks[0][1]) > 1.5 * float(bids[0][1]):
        return "Sell wall spoofing suspected"
    return None

async def analyze_symbol(symbol):
    try:
        candles = await fetch_kline(symbol)
        latest, previous = candles[-1], candles[-2]

        latest_close = float(latest[4])
        previous_close = float(previous[4])
        latest_vol = float(latest[5])

        price_change = (latest_close - previous_close) / previous_close

        if abs(price_change) > 0.02 and latest_vol > MIN_VOL:
            orderbook = await fetch_orderbook(symbol)
            spoof_alert = detect_spoofing(orderbook)

            if spoof_alert:
                alert_msg = f"⚠️ Spoofing Detected on {symbol}
{spoof_alert}
Price: {latest_close}"
                await send_telegram_alert(alert_msg)

            signal_type = "Long📈" if price_change > 0 else "Short📉"
            entry = latest_close
            tp1 = round(entry * (1 + 0.01 * (1 if price_change > 0 else -1)), 6)
            tp2 = round(entry * (1 + 0.015 * (1 if price_change > 0 else -1)), 6)
            tp3 = round(entry * (1 + 0.02 * (1 if price_change > 0 else -1)), 6)
            tp4 = round(entry * (1 + 0.03 * (1 if price_change > 0 else -1)), 6)

            msg = f"🔥 #{symbol} (x20 {signal_type}) 🔥
Entry - {entry}
Take-Profit:
🥉 TP1 {tp1}
🥈 TP2 {tp2}
🥇 TP3 {tp3}
🚀 TP4 {tp4}"
            await send_telegram_alert(msg)

    except Exception as e:
        print(f"Error analyzing {symbol}:", e)

async def main_loop():
    symbols = await fetch_all_perp_symbols()
    await send_telegram_alert("✅ Bot is live and scanning 5m Bybit perpetuals...")

    while True:
        tasks = [analyze_symbol(symbol) for symbol in symbols]
        await asyncio.gather(*tasks)
        await asyncio.sleep(300)  # 5 minutes

if __name__ == "__main__":
    asyncio.run(main_loop())
