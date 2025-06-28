from telegram import Bot
import time

# ✅ Your Telegram Bot Token and Chat ID
TELEGRAM_BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
TELEGRAM_CHAT_ID = "7186880587"  # This is your personal chat ID

bot = Bot(token=TELEGRAM_BOT_TOKEN)

def send_test_alert():
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="🚀 [TEST ALERT] Market Sniper Bot is now live!")
        print("✅ Test alert sent.")
    except Exception as e:
        print(f"❌ Failed to send test alert: {e}")

if __name__ == "__main__":
    send_test_alert()
    while True:
        # Placeholder loop to keep bot alive
        time.sleep(60)




