import asyncio
from telegram import Bot

# ✅ Telegram Bot Token and Your Personal Chat ID
TELEGRAM_BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
TELEGRAM_CHAT_ID = "7186880587"

bot = Bot(token=TELEGRAM_BOT_TOKEN)

async def send_test_alert():
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="🚀 [TEST ALERT] Market Sniper Bot is now live!")
        print("✅ Test alert sent.")
    except Exception as e:
        print(f"❌ Failed to send test alert: {e}")

if __name__ == "__main__":
    print("📡 5-Minute Sniper Bot Running...")
    asyncio.run(send_test_alert())

    # Keep your bot alive (add logic or loop as needed)
    import time
    while True:
        time.sleep(60)




