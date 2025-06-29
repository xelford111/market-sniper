import asyncio
import time
from datetime import datetime
from pybit.unified_trading import HTTP
from telegram import Bot

# --- USER CONFIG ---
TELEGRAM_BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
TELEGRAM_CHANNEL_ID = "-1002674839519"
API_KEY = "AAGZrcM0P7PXw7ox5nEkHvvRD5p1kXYSWJc"
API_SECRET = "YrmcHkJdlf3YTyFZAbwrXq9LtNGdyjz3IYZp"

TP_MULTIPLIERS = [1.02, 1.04, 1.06, 1.08]
BREAKOUT_THRESHOLD = 1.012
VOLUME_MULTIPLIER = 1.3
SLEEP_INTERVAL = 60

client = HTTP(api_key=API_KEY, api_secret=API_SECRET)
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# Send test signal
async def send_startup_message():
    await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text="✅ Market Sniper Bot is now LIVE and scanning...")

async def send_signal(symbol, direction, entry):
    tps = [round(entry * m, 6) if direction == "long" else round(entry / m, 6) for m in TP_MULTIPLIERS]
    msg = f"""🔥 #{symbol}/USDT ({'Long📈' if direction == 'long' else 'Short📉'}, x20) 🔥
Entry - {entry}
Take-Profit:
🥉 TP1 ({TP_MULTIPLIERS[0]}x): {tps[0]}
🥈 TP2 ({TP_MULTIPLIERS[1]}x): {tps[1]}
🥇 TP3 ({TP_MULTIPLIERS[2]}x): {tps[2]}
🚀 TP4 ({TP_MULTIPLIERS[3]}x): {tps[3]}"""
    await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=msg)

def get_all_symbols():
    try:
        data = client.get_instruments(category="linear")["result"]["list"]
        return [s["symbol"] for s in data if s["symbol"].endswith("USDT")]
    except Exception as e:
        print("Error fetching symbols:", e)
        return []

def get_klines(symbol):
    k = client.get_kline(category="linear", symbol=symbol, interval="1", limit=4)["result"]["list"]
    return [[float(x) for x in row] for row in k]

def get_orderbook(symbol):
    ob = client.get_orderbook(category="linear", symbol=symbol, limit=25)["result"]
    bids = sum(float(b[1]) for b in ob["b"])
    asks = sum(float(a[1]) for a in ob["a"])
    top_bid = float(ob["b"][0][1])
    top_ask = float(ob["a"][0][1])
    return bids, asks, top_bid, top_ask

def spoofing_detected(symbol):
    try:
        ob1 = client.get_orderbook(category="linear", symbol=symbol, limit=25)["result"]
        time.sleep(0.5)
        ob2 = client.get_orderbook(category="linear", symbol=symbol, limit=25)["result"]
        b1 = sum(float(x[1]) for x in ob1["b"])
        b2 = sum(float(x[1]) for x in ob2["b"])
        a1 = sum(float(x[1]) for x in ob1["a"])
        a2 = sum(float(x[1]) for x in ob2["a"])
        return abs(b2 - b1) > 50000 or abs(a2 - a1) > 50000
    except:
        return False

async def scan():
    await send_startup_message()
    while True:
        symbols = get_all_symbols()
        for symbol in symbols:
            try:
                k = get_klines(symbol)
                if len(k) < 4:
                    continue
                prev_closes = [c[4] for c in k[-4:-1]]
                avg_volume = sum(c[5] for c in k[-4:-1]) / 3
                latest = k[-1]
                open_, high, low, close, vol = latest[1], latest[2], latest[3], latest[4], latest[5]
                price_change = close / open_

                if vol < avg_volume * VOLUME_MULTIPLIER:
                    continue

                if abs(close - open_) / (high - low + 1e-8) < 0.6:
                    continue

                prev_high = max(c[2] for c in k[-4:-1])
                prev_low = min(c[3] for c in k[-4:-1])
                if price_change > 1 and close <= prev_high:
                    continue
                if price_change < 1 and close >= prev_low:
                    continue

                bids, asks, wall_bid, wall_ask = get_orderbook(symbol)

                if spoofing_detected(symbol):
                    continue

                if price_change >= BREAKOUT_THRESHOLD and bids > asks and wall_bid > wall_ask:
                    await send_signal(symbol, "long", close)
                elif price_change <= 1 / BREAKOUT_THRESHOLD and asks > bids and wall_ask > wall_bid:
                    await send_signal(symbol, "short", close)

            except Exception as e:
                print(f"{symbol} error: {e}")

        await asyncio.sleep(SLEEP_INTERVAL)

if __name__ == "__main__":
    asyncio.run(scan())

