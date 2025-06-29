import asyncio
import time
import logging
import httpx
from telegram import Bot

BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
CHANNEL_ID = "-1002111808148"

async def send_telegram_alert(message: str):
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(chat_id=CHANNEL_ID, text=message)
        print(f"[TELEGRAM SENT] {message}")
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")

async def fetch_markets(client):
    try:
        print("[INFO] Fetching market data...")
        response = await client.get("https://api.bybit.com/v5/market/tickers?category=linear")
        data = response.json()
        print("[INFO] Market data received.")
        return data.get("result", {}).get("list", [])
    except Exception as e:
        print(f"[FETCH ERROR] {e}")
        return []

async def main():
    print("[START] Bot is running.")
    transport = httpx.AsyncHTTPTransport(retries=3)
    async with httpx.AsyncClient(transport=transport, timeout=10) as client:
        while True:
            try:
                print(f"[LOOP] Heartbeat at {time.strftime('%X')}")
                markets = await fetch_markets(client)
                if not markets:
                    print("[WARN] No market data fetched.")
                else:
                    sample = markets[0]
                    symbol = sample.get("symbol", "UNKNOWN")
                    price = sample.get("lastPrice", "0")
                    msg = f"🔥 #{symbol} (Test Signal)\nEntry - {price}\n🚀 Potential pump detected."
                    await send_telegram_alert(msg)

                await asyncio.sleep(300)
            except Exception as e:
                print(f"[LOOP ERROR] {e}")
                await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
