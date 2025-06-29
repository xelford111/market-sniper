import asyncio
import httpx
import time
from datetime import datetime
import pandas as pd
from pybit.unified_trading import HTTP
from telegram import Bot

# === USER CONFIG ===
TELEGRAM_BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
TELEGRAM_CHANNEL_ID = "-1002674839519"
API_KEY = "AAGZrcM0P7PXw7ox5nEkHvvRD5p1kXYSWJc"  # Your actual Bybit key
API_SECRET = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"  # Replace with real secret

TP_MULTIPLIERS = [1.02, 1.04, 1.06, 1.08]
BREAKOUT_THRESHOLD = 1.012
VOLUME_THRESHOLD = 1.3
CHECK_INTERVAL = 60  # seconds
CANDLE_INTERVAL = "5"

client = HTTP(api_key=API_KEY, api_secret=API_SECRET)
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# === Start message ===
async def send_startup_message():
    await bot.send_message(
        chat_id=TELEGRAM_CHANNEL_ID,
        text="✅ Market Sniper Bot is now LIVE and scanning!"
    )

# === Get all USDT symbols ===
async def fetch_symbols():
    response = client.get("/v5/market/tickers", params={"category": "linear"})
    return [item["symbol"] for item in response["result"]["list"] if item["symbol"].endswith("USDT")]

# === Get latest 5-minute candles ===
async def fetch_kline(symbol):
    response = client.get("/v5/market/kline", params={
        "category": "linear",
        "symbol": symbol,
        "interval": CANDLE_INTERVAL,
        "limit": 4
    })
    if "result" not in response or "list" not in response["result"]:
        return None
    df = pd.DataFrame(response["result"]["list"], columns=[
        "timestamp", "open", "high", "low", "close", "volume", "turnover"])
    df[["open", "close", "volume"]] = df[["open", "close", "volume"]].astype(float)
    return df

# === Format message ===
def format_signal(symbol, direction, entry):
    return f"""🔥 #{symbol}/USDT ({'Long📈' if direction == 'long' else 'Short📉'}, x20) 🔥
Entry - {entry:.4f}
Take-Profit:
🥉 TP1 ({TP_MULTIPLIERS[0]}x)
🥈 TP2 ({TP_MULTIPLIERS[1]}x)
🥇 TP3 ({TP_MULTIPLIERS[2]}x)
🚀 TP4 ({TP_MULTIPLIERS[3]}x)
"""

# === Main scanner ===
async def scan():
    await send_startup_message()
    while True:
        try:
            symbols = await fetch_symbols()
            for symbol in symbols:
                df = await fetch_kline(symbol)
                if df is None or len(df) < 4:
                    continue

                latest = df.iloc[-1]
                prev_3 = df.iloc[-4:-1]
                avg_volume = prev_3["volume"].mean()
                price_change = (latest["close"] - latest["open"]) / latest["open"]
                volume_spike = latest["volume"] > avg_volume * VOLUME_THRESHOLD

                if abs(price_change) > BREAKOUT_THRESHOLD and volume_spike:
                    direction = "long" if price_change > 0 else "short"
                    msg = format_signal(symbol, direction, latest["close"])
                    await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=msg)
        except Exception as e:
            print("Error during scan:", e)
        await asyncio.sleep(CHECK_INTERVAL)

# === Run ===
if __name__ == "__main__":
    asyncio.run(scan())

