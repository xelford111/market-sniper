async def detect_spoofing(order_book):
    # Placeholder spoofing logic: flag if large orders disappear quickly
    spoofing_detected = False
    large_orders = [order for order in order_book['asks'] if order[1] > 50000]  # Mock threshold
    if len(large_orders) > 3:
        spoofing_detected = True
    return spoofing_detected



import asyncio
import httpx
import json
import time
import traceback
from datetime import datetime
from statistics import mean

import numpy as np
import pandas as pd
from telebot import TeleBot

# === CONFIGURATION ===
BOT_TOKEN = "7939062269:AAFwdMlsADkSe-6sMB0EqPfhQmw0Fn4DRus"
CHANNEL_ID = "-1002674839519"
FETCH_INTERVAL = 300  # 5-minute candles

# === TELEGRAM ALERTING ===
bot = TeleBot(BOT_TOKEN)

def send_alert(msg):
    try:
        bot.send_message(CHANNEL_ID, msg)
    except Exception as e:
        print(f"Telegram send error: {e}")

# === TEST ALERT ON STARTUP ===
send_alert("✅ [TEST ALERT] Market Sniper Bot is Live (5-minute candles, proxy enabled)")

# === MAIN LOGIC ===
async def fetch_klines(symbol):
    url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}&interval=5&limit=100"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url)
        data = r.json()
        if "result" not in data or "list" not in data["result"]:
            return []
        return data["result"]["list"]

async def fetch_symbols():
    url = "https://api.bybit.com/v5/market/instruments-info?category=linear"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url)
        data = r.json()
        return [x["symbol"] for x in data["result"]["list"] if "USDT" in x["symbol"]]

def detect_breakout(df):
    try:
        closes = df["close"].astype(float)
        highs = df["high"].astype(float)
        lows = df["low"].astype(float)
        last = closes.iloc[-1]
        prev = closes.iloc[-2]
        avg_vol = mean(abs(closes.diff().fillna(0)))
        breakout = abs(last - prev) > 1.5 * avg_vol
        volume_spike = df["volume"].astype(float).iloc[-1] > 1.5 * mean(df["volume"].astype(float).iloc[-10:])
        return breakout and volume_spike
    except Exception:
        return False

async def scan():
    symbols = await fetch_symbols()
    print(f"Scanning {len(symbols)} symbols...")
    for symbol in symbols:
        try:
            raw = await fetch_klines(symbol)
            if not raw or len(raw) < 30:
                continue
            df = pd.DataFrame(raw, columns=[
                "timestamp", "open", "high", "low", "close", "volume", "turnover"
            ])
            df["close"] = df["close"].astype(float)
            df["volume"] = df["volume"].astype(float)

            if detect_breakout(df):
                msg = f"🔥 #{symbol}/USDT (5m breakout) 🔥\nEntry - {df['close'].iloc[-1]:.4f}\nTP1 🎯 +2%\nTP2 🎯 +4%\nTP3 🎯 +6%\n🚀 TP4 +10%"
                send_alert(msg)

        except Exception as e:
            print(f"[{symbol}] scan error: {e}")
            traceback.print_exc()

async def main_loop():
    while True:
        try:
            await scan()
        except Exception as e:
            print(f"Scan loop error: {e}")
        await asyncio.sleep(FETCH_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main_loop())

