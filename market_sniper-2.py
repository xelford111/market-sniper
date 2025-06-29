import asyncio
import logging
import httpx
from telegram import Bot

# === CONFIG ===
BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
CHANNEL_ID = "-1002122557539"

async def send_test_alert():
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(chat_id=CHANNEL_ID, text="🧪 Test Signal from Sniper Bot\nThis confirms your Telegram bot is working ✅")
        print("✅ Test alert sent.")
    except Exception as e:
        logging.error(f"❌ Failed to send test alert: {e}")

async def main():
    await send_test_alert()
    # Placeholder for your main sniper bot logic (to be inserted here)
    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
