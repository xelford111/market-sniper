
import requests
import time
import logging
from pybit.unified_trading import HTTP

# === USER SETTINGS ===
TELEGRAM_BOT_TOKEN = "8091949431:AAHJDbsInstiariVEMPbKxsHFfH4zFCvDt8"
TELEGRAM_CHAT_USERNAME = "@chatxbot6363"
CHECK_INTERVAL = 300  # 5 minutes
PUMP_THRESHOLD = 0.02  # 2% price move

# === SETUP ===
session = HTTP()
logging.basicConfig(level=logging.INFO)

def get_symbols():
    try:
        res = session.get_tickers(category="linear")
        return [i["symbol"] for i in res["result"]["list"] if i["symbol"].endswith("USDT")]
    except Exception as e:
        logging.error(f"Error fetching symbols: {e}")
        return []

def get_depth(symbol):
    try:
        res = session.get_orderbook(category="linear", symbol=symbol)
        bid = float(res["result"]["b"][0][0])
        ask = float(res["result"]["a"][0][0])
        return bid, ask
    except Exception as e:
        logging.error(f"Error fetching depth: {e}")
        return 0, 0

def send_alert(symbol, entry, move, bid, ask):
    direction = "Long📈" if move == "pump" else "Short📉"
    leverage = "x20"
    tp1 = round(entry * 1.025, 6)
    tp2 = round(entry * 1.035, 6)
    tp3 = round(entry * 1.045, 6)
    tp4 = round(entry * 1.055, 6)

    message = f"""🔥 #{symbol} ({direction}, {leverage}) 🔥
Entry - {entry}
Take-Profit:
🥉 TP1 (40%) = {tp1}
🥈 TP2 (60%) = {tp2}
🥇 TP3 (80%) = {tp3}
🚀 TP4 (100%) = {tp4}"""

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_USERNAME,
            "text": message
        }
        response = requests.post(url, json=payload)
        logging.info(f"Sent alert: {symbol} | Status: {response.status_code}")
    except Exception as e:
        logging.error(f"Failed to send Telegram alert: {e}")

def check_market():
    symbols = get_symbols()
    for symbol in symbols:
        try:
            res = session.get_kline(category="linear", symbol=symbol, interval=5, limit=2)
            kline = res["result"]["list"]
            if len(kline) < 2:
                continue

            prev_close = float(kline[-2][4])
            curr_close = float(kline[-1][4])
            change = (curr_close - prev_close) / prev_close

            if abs(change) >= PUMP_THRESHOLD:
                bid, ask = get_depth(symbol)
                move = "pump" if change > 0 else "dump"
                send_alert(symbol, curr_close, move, bid, ask)

        except Exception as e:
            logging.error(f"Error checking {symbol}: {e}")

# === TEST ALERT BLOCK ===
def send_test_alert():
    send_alert("TESTCOIN/USDT", 0.1234, "pump", 0.1240, 0.1250)
    logging.info("[TEST ALERT] Sent")

# === MAIN LOOP ===
if __name__ == "__main__":
    logging.info("🚀 5-Minute Sniper Bot Running...")
    send_test_alert()
    while True:
        check_market()
        time.sleep(CHECK_INTERVAL)




