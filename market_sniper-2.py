
import requests
import time
from datetime import datetime
import json

# === Telegram Bot Configuration ===
BOT_TOKEN = "8029194:AAH1JbSInstariVEMPWPkxsHFHf4zFcvDt8"
CHAT_ID = "7186880587"

def send_telegram_message(message: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram Error: {e}")

def fetch_bybit_perpetual_data():
    url = "https://api.bybit.com/v5/market/tickers?category=linear"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json().get("result", {}).get("list", [])
        else:
            print(f"[ERROR] HTTP {response.status_code}")
            return []
    except Exception as e:
        print(f"[ERROR] Failed to fetch Bybit data: {e}")
        return []

def analyze_market(tickers):
    threshold = 3.0  # 3% change
    signals = []
    for ticker in tickers:
        symbol = ticker.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue
        try:
            price_change_percent = float(ticker.get("price24hPcnt", 0)) * 100
            if abs(price_change_percent) >= threshold:
                direction = "📈 Long" if price_change_percent > 0 else "📉 Short"
                last_price = ticker.get("lastPrice", "?")
                signals.append(f"🔥 #{symbol} ({direction}) 🔥\nLast Price: {last_price}\n24h Change: {price_change_percent:.2f}%")
        except Exception as e:
            print(f"Ticker error: {e}")
    return signals

def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Monitoring Bybit Perp Market...")
    while True:
        tickers = fetch_bybit_perpetual_data()
        signals = analyze_market(tickers)
        for signal in signals:
            send_telegram_message(signal)
        time.sleep(60)

if __name__ == "__main__":
    main()
