import asyncio
import httpx
import time
import logging

BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
CHANNEL_ID = "-1002248759670"
VOLUME_SPIKE_MULTIPLIER = 2.0  # Spike if volume is 2x avg of last 10 candles
BYBIT_URL = "https://api.bybit.com"
TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

HEADERS = {"Content-Type": "application/json"}

async def send_telegram_message(message: str):
    async with httpx.AsyncClient() as client:
        await client.post(TELEGRAM_URL, json={"chat_id": CHANNEL_ID, "text": message, "parse_mode": "Markdown"})

async def fetch_candles(symbol: str):
    try:
        url = f"{BYBIT_URL}/v5/market/kline"
        params = {
            "category": "linear",
            "symbol": symbol,
            "interval": "5",
            "limit": 15
        }
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, params=params)
            data = response.json()
            if "result" in data and "list" in data["result"]:
                return list(reversed(data["result"]["list"]))
    except Exception as e:
        logging.error(f"Error fetching candles for {symbol}: {e}")
    return None

async def get_symbols():
    try:
        url = f"{BYBIT_URL}/v5/market/instruments-info?category=linear"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            data = response.json()
            return [x["symbol"] for x in data["result"]["list"] if "USDT" in x["symbol"]]
    except Exception as e:
        logging.error(f"Error fetching symbols: {e}")
    return []

def detect_breakout(candles):
    if len(candles) < 5:
        return False

    latest = candles[-1]
    previous = candles[-2]

    latest_close = float(latest[4])
    previous_close = float(previous[4])

    # Breakout or dump logic
    return abs(latest_close - previous_close) / previous_close > 0.01  # >1% move

def is_volume_spike(candles):
    if len(candles) < 11:
        return False
    volumes = [float(c[5]) for c in candles[-11:-1]]  # last 10 before current
    avg_volume = sum(volumes) / len(volumes)
    current_volume = float(candles[-1][5])
    return current_volume > avg_volume * VOLUME_SPIKE_MULTIPLIER

async def scan_market():
    symbols = await get_symbols()
    while True:
        for symbol in symbols:
            candles = await fetch_candles(symbol)
            if candles and detect_breakout(candles) and is_volume_spike(candles):
                close_price = float(candles[-1][4])
                msg = f"🔥 *#{symbol}/USDT* Detected!
"                       f"Breakout with strong volume at *{close_price:.4f}* 🔍

"                       f"Watch for continuation or fade."
                await send_telegram_message(msg)
        await asyncio.sleep(30)

async def main():
    await send_telegram_message("🚨 Market Sniper bot started with Volume Spike filter.")
    await scan_market()

if __name__ == "__main__":
    asyncio.run(main())

