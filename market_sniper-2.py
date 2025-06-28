import asyncio
import httpx
import time
from pybit.unified_trading import HTTP
from telegram import Bot

# === CONFIGURATION ===
BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
CHANNEL_ID = "@rawcryptoalerts"
LEVERAGE = "x20"
TRANSPORT = httpx.AsyncHTTPTransport(proxy="http://proxy.zyte.com:8011")

client = HTTP()
bot = Bot(token=BOT_TOKEN)

def format_telegram_message(symbol, direction, entry, tps):
    tp_text = "\n".join([
        f"🥉 TP1 ({tps[0]}%)",
        f"🥈 TP2 ({tps[1]}%)",
        f"🥇 TP3 ({tps[2]}%)",
        f"🚀 TP4 ({tps[3]}%)",
    ])
    return f"🔥 #{symbol}/USDT ({direction}, {LEVERAGE}) 🔥\nEntry - {entry}\nTake-Profit:\n{tp_text}"

async def fetch_market_data():
    async with httpx.AsyncClient(transport=TRANSPORT, timeout=10.0) as client:
        res = await client.get("https://api.bybit.com/v5/market/tickers?category=linear")
        return res.json().get("result", {}).get("list", [])

async def fetch_orderbook(symbol):
    try:
        async with httpx.AsyncClient(transport=TRANSPORT, timeout=10.0) as client:
            res = await client.get(f"https://api.bybit.com/v5/market/orderbook?category=linear&symbol={symbol}&limit=50")
            return res.json().get("result", {})
    except:
        return {}

def detect_spoofing(orderbook):
    bids = orderbook.get("b", [])
    asks = orderbook.get("a", [])
    if not bids or not asks:
        return False
    top_bid = float(bids[0][1])
    top_ask = float(asks[0][1])
    if top_bid > 1_000_000 or top_ask > 1_000_000:
        return True
    return False

async def monitor():
    while True:
        try:
            markets = await fetch_market_data()
            for m in markets:
                symbol = m["symbol"]
                if not symbol.endswith("USDT"):
                    continue

                volume = float(m["turnover24h"])
                price = float(m["lastPrice"])
                change = float(m["price24hPcnt"]) * 100

                if volume > 5_000_000 and abs(change) > 6:
                    spoofing = False
                    orderbook = await fetch_orderbook(symbol)
                    if detect_spoofing(orderbook):
                        spoofing = True

                    direction = "Long📈" if change > 0 else "Short📉"
                    entry = f"{price:.4f}"
                    tps = [5, 10, 15, 20]
                    msg = format_telegram_message(symbol, direction, entry, tps)

                    if spoofing:
                        msg += "\n⚠️ Potential spoofing detected in order book!"

                    # 🐳 Whale detection placeholder (to be connected with wallet tracking)
                    # msg += "\n🐳 Whale activity detected!"

                    await bot.send_message(chat_id=CHANNEL_ID, text=msg)
                    print(f"✅ Alert sent for {symbol}: {direction} - {entry}")
            await asyncio.sleep(300)
        except Exception as e:
            print("❌ Error:", e)
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(monitor())
