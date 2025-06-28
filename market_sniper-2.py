
import asyncio
import aiohttp
import time
from datetime import datetime
from telegram import Bot

# === CONFIGURATION ===
TELEGRAM_BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
TELEGRAM_CHAT_ID = "7186880587"
INTERVAL = 300  # 5 minutes
SYMBOLS_ENDPOINT = "https://api.bybit.com/v5/market/tickers?category=linear"

# ✅ Public Indonesian Proxy (non-US)
PROXIES = {
    "http": "http://103.168.251.17:8080",
    "https": "http://103.168.251.17:8080"
}

bot = Bot(token=TELEGRAM_BOT_TOKEN)

async def send_telegram_alert(message):
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    except Exception as e:
        print(f"❌ Telegram Error: {e}")

def format_alert(symbol, direction, price):
    return f"""🔥 #{symbol} ({"Long📈" if direction == "long" else "Short📉"}, x20) 🔥
Entry - {price}
Take-Profit:
🥉 TP1 (40% of profit)
🥈 TP2 (60% of profit)
🥇 TP3 (80% of profit)
🚀 TP4 (100% of profit)
"""

def detect_signals(data):
    alerts = []
    for item in data.get("result", {}).get("list", []):
        symbol = item["symbol"]
        if not symbol.endswith("USDT"):
            continue
        try:
            last_price = float(item["lastPrice"])
            volume_24h = float(item["turnover24h"])
            percent_change = float(item["price24hPcnt"]) * 100
        except:
            continue

        if volume_24h > 5000000 and abs(percent_change) > 5:
            direction = "long" if percent_change > 0 else "short"
            alerts.append(format_alert(symbol, direction, last_price))
    return alerts

async def fetch_symbols():
    try:
        conn = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=conn) as session:
            proxy_url = PROXIES.get("http")
            async with session.get(SYMBOLS_ENDPOINT, proxy=proxy_url, timeout=10) as resp:
                if resp.status != 200:
                    print(f"❌ HTTP error: {resp.status}")
                    return None
                return await resp.json()
    except Exception as e:
        print(f"❌ Fetch Error: {e}")
        return None

async def run_sniper():
    await send_telegram_alert("✅ [TEST ALERT] Market Sniper Bot is live (using proxy)")
    print("🟢 Sniper running...")
    while True:
        data = await fetch_symbols()
        if data:
            alerts = detect_signals(data)
            for alert in alerts:
                await send_telegram_alert(alert)
                print(f"✅ Sent: {alert}")
        await asyncio.sleep(INTERVAL)

if __name__ == "__main__":
    asyncio.run(run_sniper())




