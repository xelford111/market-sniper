
import asyncio
import logging
import httpx
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError
import os

# ========================
# CONFIGURATION
# ========================
BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
CHANNEL_ID = "-1002674839519"  # Your Telegram channel ID (Chatxbot)
PROXY_URL = "http://proxy.scrapeops.io:5353"
PROXY_HEADERS = {
    "Proxy-Authorization": "Basic c2NyYXBlb3BzOmJmOWMzZTRhZTg0NzQ4NmRhYzVmYjcwN2FlMTIzN2M2"
}

# ========================
# TEST MESSAGE FUNCTION
# ========================
async def send_test_message():
    try:
        async with httpx.AsyncClient(proxies=PROXY_URL, headers=PROXY_HEADERS, timeout=10) as client:
            bot = Bot(token=BOT_TOKEN, request=client)
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text="✅ [TEST ALERT] Market Sniper Bot is now live using proxy!",
                parse_mode=ParseMode.HTML
            )
    except TelegramError as e:
        print(f"TelegramError: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

# ========================
# MAIN
# ========================
if __name__ == "__main__":
    asyncio.run(send_test_message())
