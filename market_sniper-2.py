import requests
import time
import logging
from telegram import Bot
import pandas as pd

# === CONFIG ===
TELEGRAM_TOKEN = "your_actual_bot_token_here"
TELEGRAM_CHAT_ID = "your_actual_chat_id_here"
SYMBOLS_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"
KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
LEVERAGE = 20
INTERVAL = "1m"
LIMIT = 50
RSI_PERIOD = 14
VOLUME_SPIKE_MULTIPLIER = 2.5
SLEEP_TIME = 60  # seconds between scans

# === SETUP ===
bot = Bot(token=TELEGRAM_TOKEN)
logging.basicConfig(level=logging.INFO)

def fetch_symbols():
    data = requests.get(SYMBOLS_URL).json()
    return [s['symbol'] for s in data['symbols'] if s['contractType'] == "PERPETUAL" and s['symbol'].endswith("USDT")]

def fetch_klines(symbol):
    params = {"symbol": symbol, "interval": INTERVAL, "limit": LIMIT}
    response = requests.get(KLINES_URL, params=params)
    return pd.DataFrame(response.json(), columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"
    ])

def calculate_rsi(closes, period=RSI_PERIOD):
    delta = closes.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def analyze(symbol):
    df = fetch_klines(symbol)
    df['close'] = df['close'].astype(float)
    df['volume'] = df['volume'].astype(float)

    latest_volume = df['volume'].iloc[-1]
    avg_volume = df['volume'].iloc[-6:-1].mean()
    volume_spike = latest_volume > avg_volume * VOLUME_SPIKE_MULTIPLIER

    df['rsi'] = calculate_rsi(df['close'])
    rsi = df['rsi'].iloc[-1]

    last = df['close'].iloc[-1]
    prev = df['close'].iloc[-2]

    # Price breakout or dump detection
    bullish_breakout = last > df['high'].astype(float).iloc[-2] and volume_spike and rsi < 65
    bearish_breakdown = last < df['low'].astype(float).iloc[-2] and volume_spike and rsi > 35

    if bullish_breakout:
        send_signal(symbol, last, "Long📈")
    elif bearish_breakdown:
        send_signal(symbol, last, "Short📉")

def send_signal(symbol, entry_price, direction):
    tp1 = round(entry_price * 1.01, 6)
    tp2 = round(entry_price * 1.02, 6)
    tp3 = round(entry_price * 1.03, 6)
    tp4 = round(entry_price * 1.04, 6)
    message = f"""
🔥 #{symbol}/USDT ({direction}, x{LEVERAGE}) 🔥
Entry - {entry_price}
Take-Profit:
🥉 TP1 ({tp1})
🥈 TP2 ({tp2})
🥇 TP3 ({tp3})
🚀 TP4 ({tp4})
"""
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    logging.info(f"Sent signal for {symbol}")

def main():
    while True:
        try:
            symbols = fetch_symbols()
            for symbol in symbols:
                analyze(symbol)
            time.sleep(SLEEP_TIME)
        except Exception as e:
            logging.error(f"Error: {e}")
            time.sleep(SLEEP_TIME)

if __name__ == "__main__":
    main()

