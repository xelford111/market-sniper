#!/usr/bin/env python3
"""Read-only HTTPS audit of a public paper-trading endpoint. NEVER sends orders."""
import json
import ssl
import statistics
import time
import urllib.request
from collections import defaultdict

URL="https://leadlag.152-42-181-163.sslip.io/api/leadlag/public"
SECS=48
POLL=3
SIGNAL_HURDLE=(3.0+2*(0.0006+0.0005)*10000+0.0002*10000)/0.6
# thresholds from leadlag_paper.py v1: >=12bps leader, >=15bps lag,
# >=3bps hypothetical net, follower move <60% of leader move.
last=None
errors=[]
snapshots=0
uniq={}
signals={}
stats=[]
start=time.monotonic()
while time.monotonic()-start < SECS:
    try:
        request=urllib.request.Request(URL,headers={"User-Agent":"leadlag-readonly-audit/1.0","Accept":"application/json"})
        with urllib.request.urlopen(request, timeout=7, context=ssl.create_default_context()) as f:
            d=json.load(f)
        if d.get("version")!="venom-leadlag-paper-v1" or d.get("mode")!="paper":
            raise ValueError("Unexpected target/version; refusing to use this data")
        last=d
        snapshots+=1
        for e in d.get("events",[]):
            if e.get("type") in ("OPEN","CLOSE") and e.get("id"):uniq[e["id"]]=e
        for s in d.get("signals",[]):
            key=(s.get("timestamp"),s.get("symbol"),s.get("direction"),s.get("lag_gap_bps"))
            signals[key]=s
        stats.append((d.get("timestamp"),d.get("status"),d.get("research",{}).get("observations",0)))
    except Exception as exc:
        errors.append(type(exc).__name__+": "+str(exc)[:140])
    time.sleep(POLL)

print("========== VENOM LEAD-LAG LIVE READ-ONLY AUDIT ==========")
print("HTTP GET only. No edits, no exchange keys, no orders.")
print("Successful snapshots:", snapshots, "errors:",len(errors))
if not last:
    print("ERROR: No usable public JSON from endpoint")
    print("Sample errors:",errors[:5])
    raise SystemExit(1)

feeds=last.get("market_feeds",{})
print("Last report UTC:", last.get("timestamp"))
print("Last engine status:",last.get("status"))
print("Feeds (status, cumulative parsed quotes):",{
    k:(v.get("status"),v.get("count")) for k,v in feeds.items()})
print("Current paper wallet:",last.get("wallet"))
print("Paper trade counters:",last.get("trades"))
print("Current open paper position:",last.get("position"))
print("Engine entry pause:",last.get("entry_pause"))
print("Research summary:",last.get("research"))
print("Total unique OPEN/CLOSE events visible:",len(uniq))
for e in sorted(uniq.values(),key=lambda x:x.get("timestamp",""))[-8:]:
    print("EVENT:", json.dumps({k:e.get(k) for k in ("timestamp","type","symbol","direction","pnl_usdt","reason")}))
print("Recent 2s/5s/10s research:",last.get("recent_studies",[])[-6:])
print("\\n========== NEAR MISSES RECORDED BY LIVE ENGINE ==========")
if "near_misses" not in last:
    print("NEAR_MISS_LOGGING_NOT_INSTALLED: backend does not report near_misses key")
else:
    near=last.get("near_misses") or []
    print("Near misses in last engine reporting window:",len(near))
    print("Near-miss total logged (bounded):",last.get("near_miss_total_logged"))
    for m in near[:12]:
        print("NEAR_MISS:", json.dumps({key:m.get(key) for key in (
          "timestamp","symbol","direction","leader_move_bps","bybit_move_bps",
          "lag_gap_bps","estimated_gap_to_net_hurdle_bps","modeled_net_bps","reason")},sort_keys=True))
    if not near:print("No near misses reported in this snapshot window.")


print("\n========== HOW CLOSE TO OPENING? ==========")
print("Current entry filters: reference leader >=12 bps, lag >=15 bps, expected net >=3 bps,")
print("follower return below 60% leader; fresh/synchronized books, adequate Bybit depth & free margin.")
print(f"Full fee/slippage/catch-up hurdle implies lag >= {SIGNAL_HURDLE:.2f} bps")
print("(this 60% catch-up is a model assumption, not proven predictability).")
print("Recent qualifying-direction signals collected:",len(signals))
sorted_signals=sorted(signals.values(),key=lambda s: s.get("expected_net_bps_scenario",-10000),reverse=True)
for s in sorted_signals[:10]:
    leader=abs(float(s.get("leader_return_bps") or 0))
    lag=abs(float(s.get("lag_gap_bps") or 0))
    bybit=abs(float(s.get("bybit_return_bps") or 0))
    expect=float(s.get("expected_net_bps_scenario") or -999)
    print(f" {s.get('symbol')} {s.get('direction')}: leader={leader:.2f}bp, "
          f"lag={lag:.2f}bp, Bybit={bybit:.2f}bp, scenarioNet={expect:+.2f}bp, "
          f"gapToLagHurdle={max(0,SIGNAL_HURDLE-lag):.2f}bp, "
          f"leaderMin={'YES' if leader>=12 else 'NO'}, "
          f"followerMin={'YES' if bybit<leader*.6 else 'NO'}")
if not sorted_signals:
    print("No recent direction-agreeing candidate signals visible in public snapshot history.")
    print("Historical signal history cannot establish all rejected setups; see near_misses if present.")
if errors:
    print("Sample fetch errors:",errors[:3])
