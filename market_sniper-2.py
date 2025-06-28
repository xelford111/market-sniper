
import asyncio
import httpx
import time
import pandas as pd
from pybit.unified_trading import HTTP
from telegram import Bot

# === SETTINGS ===
BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
CHANNEL_ID = "-1002674839519"
LEVERAGE = "x20"
PROXY = "http://scraperapi-country-us:5f5ac26a4dfbd5b42254f95f8cf7d309@proxy-server.scraperapi.com:8001"

# === TELEGRAM SETUP ===
bot = Bot(token=BOT_TOKEN, request=httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(proxy=PROXY)))

# === BYBIT SETUP ===
session = HTTP()

def get_usdt_contracts():
    markets = session.get_symbols(category="linear")["result"]["list"]
    return [m["symbol"] for m in markets if m["quoteCoin"] == "USDT" and m["contractType"] == "LinearPerpetual"]

# === SCANNER LOGIC ===
async def fetch_kline(symbol: str):
    try:
        kline = session.get_kline(category="linear", symbol=symbol, interval="5", limit=2)
        if "result" in kline:
            df = pd.DataFrame(kline["result"]["list"], columns=[
                "timestamp", "open", "high", "low", "close", "volume", "turnover"
            ])
            df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
            return df
    except Exception:
        return None

async def analyze_and_alert(symbol: str):
    df = await fetch_kline(symbol)
    if df is None or len(df) < 2:
        return

    prev, latest = df.iloc[-2], df.iloc[-1]
    volume_spike = latest["volume"] > prev["volume"] * 2
    breakout = latest["high"] > prev["high"] and latest["close"] > prev["close"]
    breakdown = latest["low"] < prev["low"] and latest["close"] < prev["close"]

    if volume_spike and (breakout or breakdown):
        direction = "Long📈" if breakout else "Short📉"
        entry = latest["close"]
        msg = f"""🔥 #{symbol}/USDT ({direction}, {LEVERAGE}) 🔥
Entry - {entry}
Take-Profit:
🥉 TP1 (40% of profit)
🥈 TP2 (60% of profit)
🥇 TP3 (80% of profit)
🚀 TP4 (100% of profit)"""
        await bot.send_message(chat_id=CHANNEL_ID, text=msg)

async def main():
    while True:
        try:
            tasks = [analyze_and_alert(symbol) for symbol in get_usdt_contracts()]
            await asyncio.gather(*tasks)
            await asyncio.sleep(60)  # wait 1 min before scanning again
        except Exception as e:
            print("Error:", e)
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
