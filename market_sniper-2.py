import asyncio
import aiohttp
import time
from datetime import datetime
import logging
from telegram import Bot

TELEGRAM_BOT_TOKEN = '7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus'
TELEGRAM_CHAT_ID = '-1002674839519'  # Channel ID

bot = Bot(token=TELEGRAM_BOT_TOKEN)

BYBIT_URL = 'https://api.bybit.com/v5/market/tickers?category=linear'
HEADERS = {'User-Agent': 'Mozilla/5.0'}

async def send_telegram_alert(message: str):
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    except Exception as e:
        print(f"Error sending alert: {e}")

async def fetch_bybit_data():
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(BYBIT_URL) as resp:
                if resp.status != 200:
                    raise Exception(f"Bad response: {resp.status}")
                data = await resp.json()
                return data.get("result", {}).get("list", [])
    except Exception as e:
        print(f"Error fetching data: {e}")
        return []

def detect_signal(ticker_data):
    signals = []
    for ticker in ticker_data:
        symbol = ticker['symbol']
        if not symbol.endswith('USDT'):
            continue
        vol = float(ticker.get('turnover24h', 0))
        last_price = float(ticker.get('lastPrice', 0))
        price_change = float(ticker.get('price24hPcnt', 0))

        if vol > 5_000_000 and abs(price_change) > 0.08:
            direction = 'Long📈' if price_change > 0 else 'Short📉'
            leverage = 'x20'
            tp_base = last_price * (1.01 if price_change > 0 else 0.99)

            tps = [tp_base * (1 + i * 0.01) if price_change > 0 else tp_base * (1 - i * 0.01) for i in range(4)]

            msg = (
                f"🔥 #{symbol}/USDT ({direction}, {leverage}) 🔥
"
                f"Entry - {last_price:.4f}
"
                f"Take-Profit:
"
                f"🥉 TP1 ({tps[0]:.4f})
"
                f"🥈 TP2 ({tps[1]:.4f})
"
                f"🥇 TP3 ({tps[2]:.4f})
"
                f"🚀 TP4 ({tps[3]:.4f})"
            )
            signals.append(msg)
    return signals

async def sniper_bot():
    await send_telegram_alert("🟢 [TEST ALERT] Market Sniper Bot is now live!")
    while True:
        data = await fetch_bybit_data()
        signals = detect_signal(data)
        for sig in signals:
            await send_telegram_alert(sig)
        await asyncio.sleep(300)  # 5-minute interval

if __name__ == "__main__":
    try:
        asyncio.run(sniper_bot())
    except Exception as e:
        print(f"Bot error: {e}")


