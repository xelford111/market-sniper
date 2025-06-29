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
API_KEY = "1Lf8RrbAZwhGz42UNY"
API_SECRET = "GCk1nVJZUOxMu5xFJP7IMj19PHeCPz4uMVSH"

TP_MULTIPLIERS = [1.02, 1.04, 1.06, 1.08]
PROXY = "http://proxy.scrapeops.io:5353"
BREAKOUT_THRESHOLD = 1.009  # Lowered from 1.012 (0.9% move)
VOLUME_SPIKE_RATIO = 1.3    # Lowered from 1.5 to 1.3

# --- INITIALIZE ---
bot = Bot(token=TELEGRAM_BOT_TOKEN)
def get_client():
    from pybit.unified_trading import HTTP
    import httpx
    transport = httpx.HTTPTransport(proxy="http://proxy.scrapeops.io:5353")
    session = httpx.Client(transport=transport)
    return HTTP(
        api_key=API_KEY,
        api_secret=API_SECRET,
        testnet=False,
        session=session
    )

client = get_client()

async def fetch_5m_candles(symbol):
    try:
        resp = await client.get_kline(category="linear", symbol=symbol, interval="5", limit=5)
        return pd.DataFrame(resp['result']['list'], columns=[
            "timestamp", "open", "high", "low", "close", "volume", "turnover"
        ])
    except Exception:
        return None

def calculate_signal_strength(price_change, volume_ratio, wall_confidence, spoof_detected):
    strength = 0
    strength += min(max((price_change - 0.009) * 2000, 0), 30)  # Up to 30 pts
    strength += min(max((volume_ratio - 1.3) * 50, 0), 30)      # Up to 30 pts
    strength += wall_confidence * 25                           # 0 to 25 pts
    if not spoof_detected:
        strength += 15
    return min(round(strength), 100)

async def send_telegram_alert(symbol, direction, entry_price, signal_strength):
    emoji = "📈" if direction == "Long" else "📉"
    tps = [round(entry_price * m, 5) if direction == "Long" else round(entry_price / m, 5) for m in TP_MULTIPLIERS]
    message = f"🔥 #{symbol} ({direction}{emoji}, x20) 🔥\n"
    message += f"Entry - {entry_price}\n"
    message += "Take-Profit:\n"
    message += f"🥉 TP1 (40%): {tps[0]}\n🥈 TP2 (60%): {tps[1]}\n🥇 TP3 (80%): {tps[2]}\n🚀 TP4 (100%): {tps[3]}\n"
    message += f"\nSignal Strength: {signal_strength}%"
    await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=message)

async def scan_market():
    symbols = [s['symbol'] for s in (await client.get_tickers(category="linear"))['result']['list'] if "USDT" in s['symbol']]
    for symbol in symbols:
        df = await fetch_5m_candles(symbol)
        if df is None or len(df) < 5:
            continue

        df = df.astype(float)
        recent = df.iloc[-1]
        prev = df.iloc[-4:-1]  # last 3 prior candles

        price_change = float(recent['close']) / float(recent['open'])
        avg_volume = prev['volume'].astype(float).mean()
        volume_ratio = float(recent['volume']) / avg_volume

        if price_change >= BREAKOUT_THRESHOLD or price_change <= (1 / BREAKOUT_THRESHOLD):
            if volume_ratio >= VOLUME_SPIKE_RATIO:
                spoof_detected = False  # placeholder
                wall_confidence = 1     # placeholder, can be 0–1 based on depth imbalance later

                direction = "Long" if price_change > 1 else "Short"
                entry_price = float(recent['close'])
                signal_strength = calculate_signal_strength(price_change, volume_ratio, wall_confidence, spoof_detected)

                await send_telegram_alert(symbol, direction, entry_price, signal_strength)

async def main():
    while True:
        await scan_market()
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())

# --- MANUAL TEST (Optional) ---
# Uncomment this to send a test signal on script start
# --- MANUAL TEST (Optional) ---
# Uncomment this to send a test signal on script start
asyncio.run(send_telegram_alert("BTCUSDT", "Long", 62000.0, 92))

