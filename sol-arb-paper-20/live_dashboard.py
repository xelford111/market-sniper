#!/usr/bin/env python3
"""Read-only terminal dashboard for multi-coin paper scanner."""
import json
import os
import time
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
BASE=Path("/root/sol-arb-paper-20-aggressive/multicoin-v3")
TZ=ZoneInfo("Australia/Melbourne")

def dollars(x):
    try: return f"USD {float(x):,.2f}"
    except (TypeError, ValueError): return "—"

def profit(x):
    try:
        x=float(x)
        return f"{'🟢' if x>0 else '🔴' if x<0 else '⚪'} {x:+,.2f} USDT"
    except (ValueError, TypeError): return "—"

def recent_events():
    try:
        with (BASE/"events.jsonl").open("rb") as fh:
            fh.seek(0,2)
            size=fh.tell()
            fh.seek(max(0,size-45000))
            lines=fh.read().splitlines()
        out=[]
        for ln in lines[-100:]:
            try:
                obj=json.loads(ln)
                if obj.get("event") in ("OPEN","CLOSE"):out.append(obj)
            except (UnicodeError,ValueError):pass
        return out[-8:]
    except OSError:return []

def get_summary():
    try:return json.loads((BASE/"summary.json").read_text())
    except (OSError,ValueError):return None

def local_time(iso):
    try:return datetime.fromisoformat(iso.replace("Z","+00:00")).astimezone(TZ)
    except (ValueError,AttributeError):return None

def main():
    try:
        while True:
            d=get_summary()
            print("\033[2J\033[H",end="")
            print("🚀 MULTI-COIN V3 ARBITRAGE  |  LIVE PAPER TRADING BOARD")
            print("🕒 Melbourne",datetime.now(TZ).strftime("%I:%M:%S %p"),"| Refresh: 5 seconds")
            print("🧪 PAPER ONLY — estimated fills, not live executable profit")
            print("═"*72)
            if d is None:
                print("⌛ Waiting for scanner summary ...")
            else:
                stamp=local_time(d.get("utc",""))
                age=(datetime.now(timezone.utc)-stamp.astimezone(timezone.utc)).total_seconds() if stamp else 999999
                print("🤖 Feed:", "🟢 RECENT" if 0<=age<180 else "🟠 STALE",
                      "| Last update:",stamp.strftime("%I:%M:%S %p") if stamp else "unknown")
                print("💰 START:",dollars(d.get("starting_equity_usdt")),
                      "| 💵 FREE:",dollars(d.get("wallet_free_usdt")),
                      "| 🔒 MARGIN:",dollars(d.get("reserved_margin_usdt")))
                print("🏦 ESTIMATED EQUITY:",dollars(d.get("estimated_equity_usdt")))
                print("✅ REALIZED NET P&L:",profit(d.get("realized_net_pnl_usdt")))
                print("📈 OPEN NET P&L:",profit(d.get("unrealized_net_pnl_usdt")))
                print("🌐 EXCHANGES:",len(d.get("supported_exchanges",[])),"/30",
                      "| 🪙 COINS:",d.get("instrument_universe","?"),
                      "| ⏱ RUN:",d.get("elapsed_minutes","?"),"minutes")
                print("🟢 OPEN PAIRS:",d.get("open_pairs",0),
                      "| ✅ CLOSED PAIRS:",d.get("completed_pairs",0))
                print("─"*72)
                print("📍 OPEN POSITIONS")
                positions=d.get("open_position_details") or []
                if not positions:print("  ⏳ No active trades")
                for p in positions:
                    print(f"  🪙 {p.get('coin','?'):7} 🟢 LONG {p.get('long','?'):15} "
                          f"🔴 SHORT {p.get('short','?'):15}  Size {dollars(p.get('notional_usdt'))}")
                print("─"*72)
                print("🧾 RECENT TRADE ACTIVITY")
                events=recent_events()
                if not events:print("  ⏳ No trades yet")
                for e in events:
                    t=local_time(e.get("utc",""))
                    clock=t.strftime("%H:%M:%S") if t else "?"
                    if e.get("event")=="OPEN":
                        line=f"Gap {e.get('verified_gap_pct','?')}% | Size {dollars(e.get('notional_usdt'))}"
                    else:
                        line=f"Realized {profit(e.get('net_realized_pnl_usdt'))}"
                    print(f"  {'🟢 OPEN' if e.get('event')=='OPEN' else '✅ CLOSE'} {clock} "
                          f"{e.get('coin','?')} {e.get('long','?')} ↔ {e.get('short','?')} | {line}")
                print("─"*72)
                print("💳 EXCHANGE FREE USDT (margin excluded)")
                for venue,balance in (d.get("funded_wallets") or {}).items():
                    print(f"  {venue:<19} {dollars(balance)}")
            print("─"*72)
            print("⚠️ Open P&L can be unknown if quotes are missing. Ctrl+C exits board only.")
            time.sleep(5)
    except KeyboardInterrupt:
        print("\nDashboard closed; scanner still running.")

if __name__=="__main__":main()
