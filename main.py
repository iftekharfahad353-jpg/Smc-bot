import requests
import time
import json
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────
import os
TOKEN   = os.environ.get("TG_TOKEN", "")
CHAT_ID = os.environ.get("TG_CHAT_ID", "")

PAIRS = [
    "BTCUSDT", "ETHUSDT", "RENDERUSDT",
    "GRTUSDT", "LTCUSDT", "SNXUSDT"
]
TIMEFRAME = "15m"   # 1m 5m 15m 1h 4h
CANDLE_LIMIT = 80
SCAN_INTERVAL = 60  # seconds between scans

sent_alerts = set()

# ── TELEGRAM ──────────────────────────────────────────────────────────────────
def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": text})
        return r.json().get("ok", False)
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

# ── BINANCE ───────────────────────────────────────────────────────────────────
def fetch_candles(symbol, interval=TIMEFRAME, limit=CANDLE_LIMIT):
    url = f"https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    data = r.json()
    candles = []
    for k in data:
        candles.append({
            "t": k[0],
            "o": float(k[1]),
            "h": float(k[2]),
            "l": float(k[3]),
            "c": float(k[4]),
        })
    return candles

def get_price(symbol):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    r = requests.get(url, timeout=5)
    return float(r.json()["price"])

# ── SMC ENGINE ────────────────────────────────────────────────────────────────
def detect_swings(candles, lookback=3):
    highs, lows = [], []
    for i in range(lookback, len(candles) - lookback):
        window = candles[i - lookback: i + lookback + 1]
        if all(c["h"] <= candles[i]["h"] for c in window):
            highs.append({"index": i, "price": candles[i]["h"]})
        if all(c["l"] >= candles[i]["l"] for c in window):
            lows.append({"index": i, "price": candles[i]["l"]})
    return highs, lows

def analyze_smc(candles):
    if len(candles) < 10:
        return []

    highs, lows = detect_swings(candles)
    last = candles[-1]
    prev = candles[-2]
    signals = []

    # BOS Bullish
    if highs and prev["c"] <= highs[-1]["price"] < last["c"]:
        signals.append({
            "type": "BOS", "direction": "BULLISH",
            "label": "🟢 Bullish BOS",
            "desc": "Break of Structure — বুলিশ ট্রেন্ড কনফার্ম"
        })

    # BOS Bearish
    if lows and prev["c"] >= lows[-1]["price"] > last["c"]:
        signals.append({
            "type": "BOS", "direction": "BEARISH",
            "label": "🔴 Bearish BOS",
            "desc": "Break of Structure — বেয়ারিশ ট্রেন্ড কনফার্ম"
        })

    # CHoCH Bullish
    if len(highs) >= 2 and prev["c"] <= highs[-2]["price"] < last["c"]:
        signals.append({
            "type": "CHoCH", "direction": "BULLISH",
            "label": "🟢 Bullish CHoCH",
            "desc": "Change of Character — বুলিশ রিভার্সাল সিগন্যাল"
        })

    # CHoCH Bearish
    if len(lows) >= 2 and prev["c"] >= lows[-2]["price"] > last["c"]:
        signals.append({
            "type": "CHoCH", "direction": "BEARISH",
            "label": "🔴 Bearish CHoCH",
            "desc": "Change of Character — বেয়ারিশ রিভার্সাল সিগন্যাল"
        })

    # FVG
    for i in range(2, len(candles)):
        c1, c3 = candles[i - 2], candles[i]
        if c1["h"] < c3["l"]:
            signals.append({
                "type": "FVG", "direction": "BULLISH",
                "label": "🟢 Bullish FVG",
                "desc": f"Fair Value Gap: {c1['h']:.4f} — {c3['l']:.4f}"
            })
        if c1["l"] > c3["h"]:
            signals.append({
                "type": "FVG", "direction": "BEARISH",
                "label": "🔴 Bearish FVG",
                "desc": f"Fair Value Gap: {c3['h']:.4f} — {c1['l']:.4f}"
            })

    # Liquidity
    if len(highs) >= 2:
        top = max(h["price"] for h in highs)
        if abs(last["h"] - top) / top < 0.001:
            signals.append({
                "type": "LIQ", "direction": "BULLISH",
                "label": "⚡ Buy-side Liquidity",
                "desc": "Buy-Side Liquidity Sweep ধরা পড়েছে"
            })
    if len(lows) >= 2:
        bot = min(l["price"] for l in lows)
        if abs(last["l"] - bot) / bot < 0.001:
            signals.append({
                "type": "LIQ", "direction": "BEARISH",
                "label": "⚡ Sell-side Liquidity",
                "desc": "Sell-Side Liquidity Sweep ধরা পড়েছে"
            })

    return signals[:3]

# ── ALERT MESSAGE ─────────────────────────────────────────────────────────────
def build_message(signal, pair, tf, price):
    now = datetime.utcnow()
    # Bangladesh time = UTC+6
    bdt_hour = (now.hour + 6) % 24
    time_str = f"{bdt_hour:02d}:{now.minute:02d} BDT"

    return (
        f"🤖 SMC Alert — {pair}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 Signal: {signal['label']}\n"
        f"📝 {signal['desc']}\n"
        f"⏱ Timeframe: {tf}\n"
        f"💰 Price: ${price}\n"
        f"⏰ Time: {time_str}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Fahad's SMC Bot 🏗️"
    )

# ── MAIN SCAN LOOP ────────────────────────────────────────────────────────────
def scan():
    print(f"🔍 Scanning {len(PAIRS)} pairs on {TIMEFRAME}...")
    found = 0

    for pair in PAIRS:
        try:
            candles = fetch_candles(pair)
            signals = analyze_smc(candles)
            price = candles[-1]["c"]
            price_str = f"{price:.2f}" if price > 1 else f"{price:.6f}"

            for sig in signals:
                # Unique key per candle period (1 alert per signal per minute-window)
                key = f"{pair}-{sig['type']}-{sig['direction']}-{TIMEFRAME}-{int(time.time() // 60)}"

                if key not in sent_alerts:
                    sent_alerts.add(key)
                    msg = build_message(sig, pair, TIMEFRAME, price_str)
                    ok = send_telegram(msg)
                    status = "✅ Sent" if ok else "❌ Failed"
                    print(f"  {status} | {pair} | {sig['label']} | ${price_str}")
                    found += 1
                    time.sleep(0.5)  # avoid spam

        except Exception as e:
            print(f"  ⚠️ Error {pair}: {e}")

    if found == 0:
        print("  No new signals this scan.")

    # Keep sent_alerts from growing too big
    if len(sent_alerts) > 500:
        sent_alerts.clear()

def main():
    print("=" * 40)
    print("  Fahad's SMC Alert Bot — STARTED")
    print(f"  Pairs: {', '.join(PAIRS)}")
    print(f"  Timeframe: {TIMEFRAME}")
    print(f"  Scan every: {SCAN_INTERVAL}s")
    print("=" * 40)

    if not TOKEN or not CHAT_ID:
        print("❌ TG_TOKEN or TG_CHAT_ID not set!")
        return

    # Send startup message
    send_telegram(
        "✅ SMC Bot Started!\n"
        f"Pairs: {', '.join(PAIRS)}\n"
        f"Timeframe: {TIMEFRAME}\n"
        "Bot is now running 24/7 🚀"
    )

    while True:
        try:
            scan()
        except Exception as e:
            print(f"Scan error: {e}")
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    main()
