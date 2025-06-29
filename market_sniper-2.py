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
PROXY = "http://proxy.scrapeops.io:5353"
API_KEY = "Z8kMq7xx3w2vyd7LC5"  # example: update with your real read-only key
API_SECRET = "vne9YuFfP2ajhNvdHyaFZFD2xPQWQ9UJAMwt"  # example: update with your real read-only secret

TP_MULTIPLIERS = [1.02, 1.04, 1.06, 1.08]
BREAKOUT_THRESHOLD = 1.012
VOLUME_SPIKE_MULTIPLIER = 2.0
SPOOFING_THRESHOLD = 2.0
CANDLE_INTERVAL = 5

# --- INIT TELEGRAM BOT ---
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# --- INIT BYBIT SESSION ---
session = HTTP(testnet=False, api_key=API_KEY, api_secret=API_SECRET)

# --- SEND TELEGRAM ALERT ---
async def send_telegram_alert(msg: str):
    try:
        await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=msg)
    except Exception as e:
        print(f"Telegram Error: {e}")

# --- FETCH CANDLE DATA ---
async def get_ohlcv(symbol: str):
    try:
        klines = session.get_kline(
            category="linear",
            symbol=symbol,
            interval=str(CANDLE_INTERVAL),
            limit=50
        )
        data = klines["result"]["list"]
        df = pd.DataFrame(data, columns=[
            "timestamp", "open", "high", "low", "close", "volume", "_", "_"])
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit='ms')
        return df
    except Exception as e:
        print(f"Error fetching OHLCV for {symbol}: {e}")
        return None

# --- SPOOFING DETECTION ---
async def detect_spoofing(symbol: str):
    try:
        ob = session.get_orderbook(symbol=symbol)
        bids = ob["result"]["b"]
        asks = ob["result"]["a"]
        if len(bids) > 10 and len(asks) > 10:
            top_bid = float(bids[0][1])
            deeper_bid = float(bids[10][1])
            top_ask = float(asks[0][1])
            deeper_ask = float(asks[10][1])
            if top_bid / deeper_bid > SPOOFING_THRESHOLD or top_ask / deeper_ask > SPOOFING_THRESHOLD:
                alert_msg = f"⚠️ Spoofing Detected on {symbol}"
                await send_telegram_alert(alert_msg)
    except Exception as e:
        print(f"Spoofing check error for {symbol}: {e}")

# --- FORMAT SIGNAL ---
def format_signal(symbol: str, entry: float, direction: str) -> str:
    emoji = "📈" if direction == "Long" else "📉"
    msg = f"🔥 #{symbol}/USDT ({direction} {emoji}, x20) 🔥\n"
    msg += f"Entry - {entry:.4f}\nTake-Profit:\n"
    for i, mult in enumerate(TP_MULTIPLIERS, 1):
        tp = entry * mult if direction == "Long" else entry / mult
        medal = ["🥉", "🥈", "🥇", "🚀"][i-1]
        msg += f"{medal} TP{i} ({int(mult*100-100)}%) = {tp:.4f}\n"
    return msg

# --- MARKET SCANNER ---
async def scan_market():
    try:
        markets = session.get_instruments_info(category="linear")["result"]["list"]
        usdt_pairs = [m["symbol"] for m in markets if "USDT" in m["symbol"]]
        async with httpx.AsyncClient(proxies={"http://": PROXY, "https://": PROXY}, timeout=15) as client:
            for symbol in usdt_pairs:
                df = await get_ohlcv(symbol)
                if df is None or len(df) < 5:
                    continue
                last = df.iloc[-1]
                prev = df.iloc[-2]
                avg_volume = df["volume"][-20:].mean()
                if last["close"] > prev["close"] * BREAKOUT_THRESHOLD and last["volume"] > avg_volume * VOLUME_SPIKE_MULTIPLIER:
                    direction = "Long"
                    msg = format_signal(symbol, last["close"], direction)
                    await send_telegram_alert(msg)
                elif last["close"] < prev["close"] / BREAKOUT_THRESHOLD and last["volume"] > avg_volume * VOLUME_SPIKE_MULTIPLIER:
                    direction = "Short"
                    msg = format_signal(symbol, last["close"], direction)
                    await send_telegram_alert(msg)
                await detect_spoofing(symbol)
    except Exception as e:
        print(f"Market scan error: {e}")

# --- MAIN LOOP ---
async def main_loop():
    await send_telegram_alert("🤖 Market Sniper Bot is now LIVE!")
    while True:
        await scan_market()
        await asyncio.sleep(60)  # 1-minute scan frequency

# --- START ---
if __name__ == "__main__":
    asyncio.run(main_loop())
