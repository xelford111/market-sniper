import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from telegram import Bot

# === CONFIG ===
BOT_TOKEN = "YOUR_BOT_TOKEN"
CHANNEL_ID = "@chatxbot6363"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SANDUSDT", "NEWTUSDT", "ARCUSDT", "XEMUSDT", "BLURUSDT", "MSTARUSDT"]
INTERVAL = "1m"
LIMIT = 50
VOLUME_SPIKE_FACTOR = 2
BREAKOUT_LOOKBACK = 20
RSI_PERIOD = 14
BASE_URL = "https://api.binance.com/api/v3/klines"

bot = Bot(token=BOT_TOKEN)

def get_klines(symbol):
    url = f"{BASE_URL}?symbol={symbol}&interval={INTERVAL}&limit={LIMIT}"
    response = requests.get(url)
    if response.status_code == 200:
        df = pd.DataFrame(response.json())
        df.columns = [
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base_volume", "taker_buy_quote_volume", "ignore"
        ]
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
        return df
    else:
        return None

def calculate_rsi(df):
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(RSI_PERIOD).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(RSI_PERIOD).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def check_signals(df, symbol):
    last_close = df["close"].iloc[-1]
    prev_close = df["close"].iloc[-2]
    max_recent = df["close"].iloc[-BREAKOUT_LOOKBACK:-1].max()
    min_recent = df["close"].iloc[-BREAKOUT_LOOKBACK:-1].min()
    avg_volume = df["volume"].iloc[-BREAKOUT_LOOKBACK:-1].mean()
    last_volume = df["volume"].iloc[-1]
    rsi_series = calculate_rsi(df)
    latest_rsi = rsi_series.iloc[-1]

    signals = []

    if last_volume > VOLUME_SPIKE_FACTOR * avg_volume:
        signals.append("📊 Volume Surge")

    if last_close > max_recent:
        signals.append("📈 Breakout")
    elif last_close < min_recent:
        signals.append("📉 Breakdown")

    if latest_rsi > 70:
        signals.append("⚠️ Overbought RSI")
    elif latest_rsi < 30:
        signals.append("⚠️ Oversold RSI")

    return signals

def send_alert(symbol, signals, last_price):
    message = (
        f"🔥 #{symbol}/USDT ({', '.join(signals)}) 🔥\n"
        f"Entry - {last_price}\n"
        f"Take-Profit:\n"
        f"🥉 TP1 (40% of profit)\n"
        f"🥈 TP2 (60% of profit)\n"
        f"🥇 TP3 (80% of profit)\n"
        f"🚀 TP4 (100% of profit)"
    )
    bot.send_message(chat_id=CHANNEL_ID, text=message)

def run():
    while True:
        for symbol in SYMBOLS:
            df = get_klines(symbol)
            if df is not None:
                signals = check_signals(df, symbol)
                if signals:
                    last_price = df["close"].iloc[-1]
                    send_alert(symbol, signals, last_price)
        time.sleep(60)

if __name__ == "__main__":
    run()

