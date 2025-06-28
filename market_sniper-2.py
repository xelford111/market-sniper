import requests
import pandas as pd
import time
import logging
from datetime import datetime
from telegram import Bot

# === CONFIG ===
BOT_TOKEN = 'YOUR_BOT_TOKEN_HERE'
CHANNEL_USERNAME = '@chatxbot6363'  # Use @channelusername (not invite link)
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'SOLUSDT', 'DOGEUSDT']  # Add more if needed
INTERVAL = '1m'
LIMIT = 50
DELAY = 30  # seconds
BASE_URL = 'https://api.binance.com/api/v3/klines'

bot = Bot(token=BOT_TOKEN)

# === UTILS ===
def fetch_klines(symbol):
    url = f"{BASE_URL}?symbol={symbol}&interval={INTERVAL}&limit={LIMIT}"
    r = requests.get(url)
    if r.status_code != 200:
        logging.warning(f"Could not fetch {symbol} - {r.status_code}")
        return None
    df = pd.DataFrame(r.json(), columns=[
        'time', 'open', 'high', 'low', 'close', 'volume', 
        '_', '_', '_', '_', '_', '_'
    ])
    df['close'] = df['close'].astype(float)
    df['volume'] = df['volume'].astype(float)
    return df

def detect_spike(df):
    if df is None or len(df) < 3:
        return False, None
    v_now = df['volume'].iloc[-1]
    v_avg = df['volume'].iloc[:-1].mean()
    pct_diff = (v_now - v_avg) / v_avg * 100
    return pct_diff > 250, round(pct_diff, 1)

def send_signal(symbol, pct, direction):
    emoji = '📈' if direction == 'long' else '📉'
    entry = df['close'].iloc[-1]
    t = f"""
🔥 #{symbol}/USDT ({direction.capitalize()}{emoji}, x20) 🔥
Entry - {entry}
Take-Profit:
🥉 TP1 (40%)
🥈 TP2 (60%)
🥇 TP3 (80%)
🚀 TP4 (100%)
Spike: {pct}%
"""
    bot.send_message(chat_id=CHANNEL_USERNAME, text=t)

# === MAIN LOOP ===
print("Bot running...")
while True:
    for symbol in SYMBOLS:
        df = fetch_klines(symbol)
        spike, pct = detect_spike(df)
        if spike:
            direction = 'long' if df['close'].iloc[-1] > df['close'].iloc[-2] else 'short'
            send_signal(symbol, pct, direction)
    time.sleep(DELAY)
