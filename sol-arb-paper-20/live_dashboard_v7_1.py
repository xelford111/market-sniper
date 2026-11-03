#!/usr/bin/env python3
"""Read-only V7 paper status dashboard. Does not contact exchange or alter engine."""
import argparse,json,os,time
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo

TZ=ZoneInfo("Australia/Melbourne")
DEFAULT_ROOT="/root/sol-arb-paper-20-aggressive/multicoin-v7"

def amt(value):
    try:return f"{float(value):,.2f}"
    except (TypeError,ValueError):return "—"

def pcol(value):
    if value is None:return "⚪ —"
    return ("🟢" if value>0 else "🔴" if value<0 else "⚪")+f" {float(value):+,.2f}"

def read_json(p):
    try:return json.loads(p.read_text())
    except (OSError,ValueError):return None

def age_report(text):
    if not text:return None
    try:
        a=datetime.fromisoformat(text.replace("Z","+00:00"))
        return (datetime.now(timezone.utc)-a).total_seconds()
    except (TypeError,ValueError):return None

def last_events(path,count=8):
    try:
        with path.open("rb") as f:
            f.seek(0,2)
            end=f.tell()
            f.seek(max(0,end-100000))
            lines=f.read().splitlines()[-150:]
        events=[]
        for line in lines:
            try:
                ev=json.loads(line)
                if ev.get("kind") in ("OPEN","CLOSE"):
                    events.append(ev)
            except (ValueError,UnicodeError):pass
        return events[-count:]
    except OSError:return []

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--root",default=DEFAULT_ROOT)
    a.add_argument("--refresh",type=float,default=5.0)
    opts=a.parse_args()
    if opts.refresh<2:a.error("refresh >= 2s")
    root=Path(opts.root)
    try:
        while True:
            d=read_json(root/"summary.json")
            print("\033[2J\033[H",end="")
            print("🚀 V7.1 | FIVE-WALLET PAPER ARBITRAGE RESEARCH")
            print("🕒 Melbourne:",datetime.now(TZ).strftime("%d %b %I:%M:%S %p"),
                  "| 🔄 dashboard refresh",opts.refresh,"sec")
            print("🧪 PAPER ONLY — market samples are NOT guaranteed executable")
            print("═"*76)
            if d is None:
                print("⏳ Waiting for V7 engine to write summary.json")
            else:
                age=age_report(d.get("utc"))
                is_up=age is not None and 0<=age<=125
                print("📡 DATA:", "🟢 RECENT" if is_up else "🟠 STALE",
                      "| Last report age:",f"{age:.0f}s" if age is not None else "?")
                print(f"💰 START: {amt(d.get('starting_equity_usdt'))} USDT"
                      f"   ⚡ {d.get('leverage_x','?')}×"
                      f"   🔒 {100*d.get('collateral_cap_per_wallet',0):.0f}% collateral max/leg")
                print("✅ REALIZED NET:",pcol(d.get("realized_net_pnl_usdt")),"USDT")
                print("📈 OPEN NET MARK:",pcol(d.get("unrealized_exit_net_pnl_usdt")),"USDT")
                print("🏦 MARKED EQUITY:",amt(d.get("estimated_marked_equity_usdt")),"USDT")
                print("💵 FREE:",amt(d.get("free_equity_usdt")),"USDT",
                      "| 🧷 RESERVED MARGIN:",amt(d.get("reserved_margin_usdt")),"USDT")
                print(f"🟢 OPEN PAIRS: {d.get('open_pairs',0)}    "
                      f"✅ CLOSED: {d.get('closed_pairs',0)}    "
                      f"🏆 WINS: {d.get('wins',0)}    "
                      f"🔴 LOSSES: {d.get('losses',0)}")
                print("🪙 UNIVERSE:",d.get("coin_universe","?"),
                      "| 🔄 SCANS:",d.get("cycles",0),
                      "| 🔍 TICKER IDEAS:",d.get("candidate_count_total",0))
                if d.get("paused_reason"):
                    print("🛑 NEW PAPER ENTRIES PAUSED:",d["paused_reason"])
                print("─"*76)
                print("💳 SIMULATED WALLET FREE BALANCES")
                for v,balance in (d.get("funded_wallets") or {}).items():
                    status=(d.get("venue_status") or {}).get(v,{})
                    icon="🟢" if status.get("status") in ("UP","READY") else "🟠"
                    print(f"  {icon} {v:<15} {amt(balance):>12} USDT"
                          f"  {status.get('status','unknown')}")
                print("─"*76)
                print("📍 OPEN HEDGED POSITIONS")
                positions=d.get("positions") or []
                if not positions:print("  ⏳ No positions currently opened")
                for p in positions[:6]:
                    mark=p.get("mark") or {}
                    print(f"  🪙 {p.get('coin','?'):7} 🟢 {p.get('long','?'):<10}"
                          f" ↔ 🔴 {p.get('short','?'):<10}"
                          f" Size/leg: {amt(p.get('notional_per_leg_usdt'))} USDT"
                          f"  Mark: {pcol(mark.get('net_usdt'))}")
                print("─"*76)
                print("🔎 TOP OBSERVED PRICE GAPS (TICKERS ONLY, UNVERIFIED)")
                observed=d.get("top_discovery") or []
                if not observed:print("  ⏳ No qualifying ideas in latest scan")
                for p in observed[:8]:
                    print(f"  📍 {p.get('coin','?'):<9}"
                          f"{p.get('buy','?'):<12} → {p.get('sell','?'):<12}"
                          f"gap {p.get('discovery_gap_pct',0):.3f}%")
                print("─"*76)
                print("📚 FRESH BOOK VALIDATIONS (SCENARIO, NOT PREDICTED PROFIT)")
                checks=d.get("book_validations") or []
                if not checks:print("  ⏳ No confirmed book checks yet")
                for p in checks[-6:]:
                    mode="🧭 SAMPLE ONLY" if p.get("diagnostic_only") else "✅ ENTRY BOOK VALIDATED"
                    print(f"  {mode} {p.get('coin','?'):<8}"
                          f" {p.get('buy','?')} → {p.get('sell','?')}"
                          f" fresh book gap {p.get('gross_gap_pct',0):.3f}%")
                    if not p.get("diagnostic_only"):
                        print("      Full-convergence scenario:",
                              p.get("full_convergence_scenario_usdt"),"USDT (not expected P&L)")
                print("─"*76)
                print("🧮 RESEARCH GAPS ≥0.15% — COSTED FRESH BOOKS")
                print("  Maker = optimistic fee-only scenario; fills NOT guaranteed.")
                research=d.get("research_samples") or []
                if not research:
                    print("  ⏳ No depth/cost research samples yet")
                for x in research[-8:][::-1]:
                    n=x.get("notional_per_leg_usdt")
                    if n is None:
                        print(f"  ⚪ {x.get('coin','?'):<8} "
                              f"{x.get('buy','?')} → {x.get('sell','?')}"
                              f" insufficient size / {x.get('reason','?')}")
                        continue
                    taker=x.get("taker_full_convergence_usdt")
                    maker=x.get("maker_fee_only_upper_bound_usdt")
                    repeat=x.get("positive_samples_15m_including_current",0)
                    print(f"  📍 {x.get('coin','?'):<8}"
                          f" {x.get('buy','?')} → {x.get('sell','?')}"
                          f" book {x.get('fresh_book_gap_pct',0):.3f}%"
                          f" size/leg {amt(n)} USDT"
                          f" | seen {repeat}× /15m")
                    print(f"     🔵 Taker fully-converged: {pcol(taker)} USDT"
                          f" | 🧪 Maker fee-only upper bound: {pcol(maker)} USDT")
                print("─"*76)
                print("⚠️ BOOK/ENTRY REJECTIONS")
                for key,value in sorted((d.get("diagnostics") or {}).items(),
                                        key=lambda x:-x[1])[:8]:
                    print(f"  {key:<38} {value}")
                print("─"*76)
                print("🧾 LAST TRADE EVENTS")
                evs=last_events(root/"events.jsonl")
                if not evs:print("  ⏳ No opening or closing events")
                for e in evs:
                    if e["kind"]=="OPEN":
                        print(f"  🟢 OPEN {e.get('coin')} {e.get('long')} ↔ {e.get('short')}"
                              f"  {e.get('gross_gap_pct')}% gross")
                    else:
                        print(f"  {'🟢' if e.get('net_usdt',0)>0 else '🔴'} CLOSE"
                              f" {e.get('coin')} {pcol(e.get('net_usdt'))} USDT "
                              f" {e.get('reason')}")
            print()
            print("🛑 Ctrl+C closes only this screen. ⚠️ $25 is not a guaranteed loss cap.")
            time.sleep(opts.refresh)
    except KeyboardInterrupt:
        print("\nDashboard closed; paper engine unaffected.")

if __name__=="__main__":
    main()
