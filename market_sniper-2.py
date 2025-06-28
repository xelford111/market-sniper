import asyncio
from telegram import Bot

API_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
CHANNEL_ID = "-1002674839519"  # Chatxbot channel ID

bot = Bot(token=API_TOKEN)

async def main():
    symbol = "BTC"
    direction = "Long📈"
    leverage = "x20"
    entry_price = "67200"

    # Send formatted signal to Telegram
    await bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"🔥 #{{symbol}}/USDT ({{direction}}, {{leverage}}) 🔥\n"
             f"Entry - {{entry_price}}\n"
             f"Take-Profit:\n"
             f"🥉 TP1 (40%)\n"
             f"🥈 TP2 (60%)\n"
             f"🥇 TP3 (80%)\n"
             f"🚀 TP4 (100%)"
    )

if __name__ == "__main__":
    asyncio.run(main())

