#!/usr/bin/env python3
"""One-hour retrospective RESEARCH replay: five 1,000-USDT wallets, 20x.
WARNING: 1m candle CLOSES are not executable bids/asks or synchronized fills.
Hypothetical paired trades only. No credentials, no exchange order methods.
"""
import argparse
import concurrent.futures
import csv
import datetime as dt
import json
import math
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

VENUE_CANDIDATES=["binanceusdm","bybit","okx","bitget","gate","mexc",
                  "phemex","kucoinfutures","bingx","blofin"]
COINS=("BTC ETH SOL XRP DOGE BNB ADA LINK AVAX LTC TRX DOT BCH UNI XLM ETC "
       "APT ARB OP SUI NEAR FIL ATOM ICP AAVE PEPE SHIB INJ POL TON "
       "WIF BONK FET RUNE GRT SEI TIA STX JUP ENA MKR ALGO HBAR ONDO NEO "
       "DYDX ZEC DASH COMP SNX KAVA GALA AXS XTZ EGLD MANA SAND LDO "
       "FLOKI WLD PENDLE JASMY RAY PYTH STRK ZRO ZK CFX CRV GMX "
       "ENS SUSHI YFI QTUM MASK ROSE CELO MINA ZIL KSM BLUR ORDI"
      ).split()
NUM_WALLETS=5
WALLET_SEED=1000.0
LEVERAGE=20.0
FEE=0.0006
SLIPPAGE=0.0005
ENTRY_GAP=0.006 # 0.60% indicative gap. Costs model ~0.44% notional if converges.
MIN_PAIR_NOTIONAL=30.0
CAPITAL_FRACTION=0.98 # nearly full wallet per side; rest is fee/buffer
MAX_HOLD_BARS=6
TAKE_PROFIT=2.0
STOP_LOSS=-100.0
LIQ_MAINTENANCE_FRACTION=0.005
ENDPOINT_TIMEOUT=14000

def utc(tsms):
    return dt.datetime.fromtimestamp(tsms/1000,tz=dt.timezone.utc).isoformat()

def is_good_market(m):
    return (m.get("swap") is True and m.get("linear") is True and
            m.get("quote")=="USDT" and m.get("settle")=="USDT" and
            m.get("active") is not False and m.get("base") in COINS)

def setup_venue(venue,since):
    import ccxt
    result={"venue":venue,"ok":False}
    try:
        ex=getattr(ccxt,venue)({"enableRateLimit":True,"timeout":ENDPOINT_TIMEOUT,
                               "options":{"defaultType":"swap"}})
        ex.load_markets()
        if not ex.has.get("fetchOHLCV") or "1m" not in ex.timeframes:
            raise RuntimeError("1m historical candles unavailable")
        mapping={}
        for symbol,m in ex.markets.items():
            if is_good_market(m) and m["base"] not in mapping:
                mapping[m["base"]]=symbol
        if len(mapping)<15:raise RuntimeError("too few compatible USDT perpetuals")
        anchor=mapping.get("SOL",mapping.get("BTC"))
        if not anchor:raise RuntimeError("no SOL/BTC perp")
        bars=ex.fetch_ohlcv(anchor,"1m",since=since,limit=65)
        if len(bars)<35:raise RuntimeError("not enough 1m candles")
        result.update(ok=True,ex=ex,mapping=mapping,
                      initial_anchor_candles=bars,supported=len(mapping))
    except Exception as e:
        result["error"]=type(e).__name__+": "+str(e)[:130]
    return result

def collect_venue(venue_data,coins,since,end):
    ex=venue_data["ex"]
    mapping=venue_data["mapping"]
    venue=venue_data["venue"]
    observed={}
    errors=[]
    for coin in coins:
        if coin not in mapping:continue
        try:
            bars=ex.fetch_ohlcv(mapping[coin],"1m",since=since,limit=65)
            prices={}
            for b in bars:
                t=int(b[0])
                if since<=t<end and b[4] is not None:
                    px=float(b[4])
                    if math.isfinite(px) and px>0:
                        prices[t]=px
            if len(prices)>=25:
                observed[coin]=prices
        except Exception as e:
            if len(errors)<12:errors.append(f"{coin}: {type(e).__name__}: {str(e)[:80]}")
    return {"venue":venue,"prices":observed,"errors":errors,
            "markets_covered":len(observed)}

def record_mark(pos,price_a,price_b):
    qty=pos["qty"]
    pa=price_a*(1-SLIPPAGE)
    pb=price_b*(1+SLIPPAGE)
    gross_a=qty*(pa-pos["entry_long"])
    gross_b=qty*(pos["entry_short"]-pb)
    close_fees=FEE*qty*(pa+pb)
    return (gross_a+gross_b-pos["fees_open"]-close_fees,
            gross_a,gross_b,FEE*qty*pa,FEE*qty*pb,pa,pb)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="sol-arb-paper-20/reports/last_hour_5_wallet_20x.json")
    p.add_argument("--max-coins",type=int,default=75)
    p.add_argument("--fixture",action="store_true")
    args=p.parse_args()
    reportpath=Path(args.out)
    reportpath.parent.mkdir(parents=True,exist_ok=True)
    now_min=(int(time.time()*1000)//60000)*60000
    # 60 completed candles: [T-60min, T); exclude incomplete present minute
    since=now_min-60*60000
    end=now_min
    print("🧪 HISTORICAL 60-MINUTE CANDLE REPLAY — NOT EXECUTABLE ARBITRAGE",flush=True)
    print("💰 5 wallets × 1,000 USDT | 20x leverage | max 98% wallet collateral+fees",flush=True)
    print("📅 UTC",utc(since),"to",utc(end),"| 1m closes | no real orders",flush=True)

    candidates=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(VENUE_CANDIDATES)) as pool:
        futures={v:pool.submit(setup_venue,v,since) for v in VENUE_CANDIDATES}
        for v in VENUE_CANDIDATES:
            r=futures[v].result()
            candidates.append(r)
            print("🌐 CHECK",v,"✅" if r["ok"] else "❌",
                  r.get("supported",r.get("error","?")),flush=True)
    selected=[r for r in candidates if r["ok"]][:NUM_WALLETS]
    errors={r["venue"]:r.get("error") for r in candidates if not r["ok"]}
    if len(selected)<2:
        raise SystemExit("ERROR: Fewer than two public venues available; not manufacturing backtest data")
    wallet_venues=[r["venue"] for r in selected]
    if len(selected)<5:
        print("⚠️ Only",len(selected),"exchanges available; inactive wallets are held as cash",flush=True)
    counts=Counter()
    for r in selected:
        counts.update(r["mapping"].keys())
    coins=[coin for coin in COINS if counts[coin]>=2][:args.max_coins]
    if not coins:raise SystemExit("No common perp symbols for pair comparisons")

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(selected)) as pool:
        jobs={r["venue"]:pool.submit(collect_venue,r,coins,since,end) for r in selected}
        datasets={v:jobs[v].result() for v in wallet_venues}
    for venue,data in datasets.items():
        print("📚 HISTORY",venue,"coin series",data["markets_covered"],
              "errors",len(data["errors"]),flush=True)
    pxmap={v:datasets[v]["prices"] for v in wallet_venues}

    # Five fixed wallets even if a venue is offline.
    wallets={v:WALLET_SEED for v in wallet_venues}
    for n in range(NUM_WALLETS-len(wallets)):
        wallets[f"UNASSIGNED-{n+1}"]=WALLET_SEED

    positions=[]
    trades=[]
    observations=[]
    event_counts=Counter()
    max_gaps={}
    snapshots=0
    for minute in range(since,end,60000):
        # Mark existing positions using this minute's indicative closes.
        for pos in list(positions):
            coin=pos["coin"]
            long_v=pos["long"]
            short_v=pos["short"]
            a=pxmap.get(long_v,{}).get(coin,{}).get(minute)
            b=pxmap.get(short_v,{}).get(coin,{}).get(minute)
            if a is None or b is None:
                event_counts["unpriced_position_minutes"]+=1
                continue
            mark=record_mark(pos,a,b)
            net,ga,gb,fee_a,fee_b,exit_a,exit_b=mark
            age=(minute-pos["entry_time"])//60000
            # Hypothetical isolated liquidation when a candle-close mark shows
            # leg equity <0.5% of gross notional. Not intraminute liquidation.
            liq_a=(pos["margin_long"]+ga) <= (qty_for_margin:=pos["qty"]*a*LIQ_MAINTENANCE_FRACTION)
            liq_b=(pos["margin_short"]+gb) <= pos["qty"]*b*LIQ_MAINTENANCE_FRACTION
            action=None
            if liq_a or liq_b:action="APPROX_LIQUIDATION"
            elif net>=TAKE_PROFIT:action="TAKE_PROFIT"
            elif net<=STOP_LOSS:action="STOP_LOSS"
            elif age>=MAX_HOLD_BARS:action="MAX_HOLD"
            elif minute==end-60000:action="FINAL_MARK"
            if action is None:continue
            # Explicit cash accounting: open collateral removed from free balances.
            long_return=max(0.0,pos["margin_long"]+ga-fee_a)
            short_return=max(0.0,pos["margin_short"]+gb-fee_b)
            wallets[long_v]+=long_return
            wallets[short_v]+=short_return
            realized=(long_return+short_return
                      -pos["margin_long"]-pos["margin_short"]-pos["fees_open"])
            closed={"coin":coin,"long":long_v,"short":short_v,
                    "entry_utc":utc(pos["entry_time"]),"exit_utc":utc(minute),
                    "held_minutes":int(age),"entry_gap_pct":round(pos["entry_gap"]*100,4),
                    "notional_long":round(pos["entry_long"]*pos["qty"],2),
                    "notional_short":round(pos["entry_short"]*pos["qty"],2),
                    "net_usdt":round(realized,4),"exit_reason":action,
                    "entry_long_px":round(pos["entry_long"],8),
                    "entry_short_px":round(pos["entry_short"],8),
                    "exit_long_px":round(exit_a,8),
                    "exit_short_px":round(exit_b,8)}
            trades.append(closed)
            event_counts[action]+=1
            positions.remove(pos)

        # Select best price gaps among same timestamp 1m closes.
        # This is *NOT* synchronous quote data; it can overstate spreads.
        ideas=[]
        for coin in coins:
            available=[]
            for v in wallet_venues:
                p=pxmap.get(v,{}).get(coin,{}).get(minute)
                if p is not None:available.append((v,p))
            if len(available)<2:continue
            snapshots+=1
            median=statistics.median(p for v,p in available)
            # Exclude extremely divergent marks that may be symbols/feeds mismatch.
            available=[(v,p) for v,p in available if abs(p/median-1)<0.025]
            if len(available)<2:continue
            low=min(available,key=lambda z:z[1])
            high=max(available,key=lambda z:z[1])
            if low[0]==high[0]:continue
            gap=high[1]/low[1]-1
            if gap<0:continue
            key=(coin,low[0],high[0])
            old=max_gaps.get(key,0)
            max_gaps[key]=max(old,gap)
            if gap>=0.002:
                observations.append({"utc":utc(minute),"coin":coin,
                    "buy":low[0],"sell":high[0],"gap_pct":round(gap*100,4)})
            if gap>=ENTRY_GAP and gap<=0.025:
                ideas.append((gap,coin,low,high))
        ideas.sort(reverse=True)
        active_coins={p["coin"] for p in positions}
        used={p[k] for p in positions for k in ("long","short")}
        for gap,coin,(buy,cheap),(sell,expensive) in ideas:
            event_counts["entry_signals"]+=1
            if coin in active_coins or buy in used or sell in used:
                event_counts["capital_busy"]+=1
                continue
            if wallets[buy]<=0 or wallets[sell]<=0:continue
            # Match base quantity, using most of BOTH wallets at 20x.
            max_quantity=min(wallets[buy]*CAPITAL_FRACTION/(cheap*(1/LEVERAGE+FEE+SLIPPAGE)),
                             wallets[sell]*CAPITAL_FRACTION/(expensive*(1/LEVERAGE+FEE+SLIPPAGE)))
            if max_quantity*cheap<MIN_PAIR_NOTIONAL:continue
            qty=max_quantity
            entry_long=cheap*(1+SLIPPAGE)
            entry_short=expensive*(1-SLIPPAGE)
            margin_long=qty*entry_long/LEVERAGE
            margin_short=qty*entry_short/LEVERAGE
            fee_long=qty*entry_long*FEE
            fee_short=qty*entry_short*FEE
            if wallets[buy]<margin_long+fee_long or wallets[sell]<margin_short+fee_short:
                continue
            wallets[buy]-=margin_long+fee_long
            wallets[sell]-=margin_short+fee_short
            positions.append({"coin":coin,"long":buy,"short":sell,
                 "entry_time":minute,"qty":qty,"entry_gap":gap,
                 "entry_long":entry_long,"entry_short":entry_short,
                 "margin_long":margin_long,"margin_short":margin_short,
                 "fees_open":fee_long+fee_short})
            used.add(buy);used.add(sell);active_coins.add(coin)
            event_counts["entries"]+=1

    # Any positions still open at last tick are NOT realized and must be counted
    # as reserved collateral, not called profit.
    unrealized=0.0
    marked=0
    reserved=sum(p["margin_long"]+p["margin_short"] for p in positions)
    for pos in positions:
        a=pxmap.get(pos["long"],{}).get(pos["coin"],{}).get(end-60000)
        b=pxmap.get(pos["short"],{}).get(pos["coin"],{}).get(end-60000)
        if a is not None and b is not None:
            net,*_=record_mark(pos,a,b)
            unrealized+=net
            marked+=1
    free=sum(wallets.values())
    # Entry fees already paid at opening; mark includes them. For estimated
    # equity, add back previously charged entry fees to avoid double counting.
    open_fees=sum(p["fees_open"] for p in positions)
    estimated_equity=free+reserved+unrealized+open_fees if marked==len(positions) else None
    realized=sum(t["net_usdt"] for t in trades)
    winners=sum(t["net_usdt"]>0 for t in trades)
    summary={
        "status":"INDICATIVE CANDLE REPLAY - NOT VALIDATED EXECUTABLE ARBITRAGE",
        "data_utc_start":utc(since),"data_utc_end_exclusive":utc(end),
        "window_minutes":60,"data_type":"1-minute public OHLCV trade closes (not order books)",
        "five_wallets_seed_usdt":WALLET_SEED,"total_start_usdt":5000,
        "leverage":LEVERAGE,"capital_fraction":CAPITAL_FRACTION,
        "assumed_taker_fee_per_fill":FEE,"assumed_slippage_per_fill":SLIPPAGE,
        "entry_min_gross_spread_pct":ENTRY_GAP*100,
        "selected_exchanges":wallet_venues,
        "offline_exchanges":errors,"wallets_final_free_usdt":{k:round(v,2) for k,v in wallets.items()},
        "coins_attempted":len(coins),
        "coins_with_2plus_venues":sum(1 for c in coins if sum(c in data["prices"] for data in datasets.values())>=2),
        "exchange_coin_series":{v:d["markets_covered"] for v,d in datasets.items()},
        "exchange_fetch_errors":{v:d["errors"] for v,d in datasets.items()},
        "aligned_coin_minutes":snapshots,
        "spreads_above_0_2_pct":len(observations),
        "total_entry_signals":event_counts["entry_signals"],
        "hypothetical_trades_completed":len(trades),
        "hypothetical_winners":winners,
        "hypothetical_losses":len(trades)-winners,
        "hypothetical_realized_net_usdt":round(realized,2),
        "hypothetical_marked_equity_usdt":round(estimated_equity,2) if estimated_equity is not None else None,
        "hypothetical_return_pct":round((estimated_equity/5000-1)*100,3) if estimated_equity is not None else None,
        "remaining_open_positions":len(positions),
        "close_reasons":dict(event_counts),
        "top_observed_gaps":sorted(observations,key=lambda x:x["gap_pct"],reverse=True)[:20],
        "top_trades":sorted(trades,key=lambda x:x["net_usdt"],reverse=True)[:10],
        "bottom_trades":sorted(trades,key=lambda x:x["net_usdt"])[:10],
        "closed_trades":trades,
        "limitations":[
            "OHLCV candles only; price close across venues is not a synchronous executable bid/ask.",
            "Entry uses known candle close and is subject to look-ahead/execution bias.",
            "No historical order-book depth, contract size/minimum lot, funding, liquidation fees, exchange-specific fee schedule, per-venue access or live order slippage.",
            "One-minute cadence misses intraminute margin breaches and may dramatically understate liquidation risks at 20x.",
            "Near-full-wallet collateral use leaves little room for adverse movement or fees.",
            "20x leveraged pair is NOT risk-free arbitrage; simultaneous entries/exits may fail.",
            "Figures are hypothetical research only and cannot establish actual realized profitability."
        ]
    }
    reportpath.write_text(json.dumps(summary,indent=2))
    csvpath=reportpath.with_suffix(".csv")
    if trades:
        with csvpath.open("w",newline="") as f:
            w=csv.DictWriter(f,fieldnames=trades[0].keys())
            w.writeheader();w.writerows(trades)
    print("\n========== FINAL HISTORICAL CANDLE REPLAY ==========",flush=True)
    keys=["data_utc_start","data_utc_end_exclusive","selected_exchanges",
          "exchange_coin_series","aligned_coin_minutes","spreads_above_0_2_pct",
          "total_entry_signals","hypothetical_trades_completed","hypothetical_winners",
          "hypothetical_realized_net_usdt","hypothetical_marked_equity_usdt",
          "hypothetical_return_pct","close_reasons"]
    for k in keys:
        print(k,":",json.dumps(summary.get(k)),flush=True)
    print("💾",reportpath,flush=True)
    print("⚠️ Historical 1m CLOSE prices are not executable quotes. Do not treat P&L as real.",flush=True)

if __name__=="__main__":
    main()
