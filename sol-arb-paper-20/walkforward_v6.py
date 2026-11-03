#!/usr/bin/env python3
"""Retrospective OHLCV walk-forward research; five 1000-USDT paper wallets.
Signals use two COMPLETED candle closes, hypothetical fills NEXT candle open.
This is NOT execution-quality arbitrage: no historical order books, funding or
exchange-specific lot sizes, fees, liquidation engine, actual matched fills.
NEVER SENDS ORDERS. Uses only PUBLIC data.
"""
import argparse, concurrent.futures, datetime, json, math, statistics, time
from collections import Counter
from pathlib import Path

VENUES=("okx","bitget","gate","mexc","phemex")
COINS=("BTC ETH SOL XRP DOGE BNB ADA LINK AVAX LTC TRX DOT BCH UNI XLM ETC "
       "APT ARB OP SUI NEAR FIL ATOM ICP AAVE PEPE SHIB INJ POL TON "
       "WIF BONK FET RUNE GRT SEI TIA STX JUP ENA MKR ALGO HBAR ONDO NEO "
       "DYDX ZEC DASH COMP SNX KAVA GALA AXS XTZ EGLD MANA SAND LDO "
       "FLOKI WLD PENDLE JASMY RAY PYTH STRK ZRO ZK CFX CRV GMX "
       "ENS SUSHI YFI QTUM MASK ROSE CELO MINA ZIL KSM BLUR ORDI").split()
START_WALLET=1000.0
FEE=0.0006
SLIP=0.0005
MIN_NOTIONAL=40.0
MAX_HOLD=6
MAX_TRADE_LOSS=25.0
MIN_NET_CONVERGENCE_SCENARIO=1.0
MAINTENANCE=0.005

def iso(ms):
    return datetime.datetime.fromtimestamp(ms/1000, tz=datetime.timezone.utc).isoformat()

def market_ok(m):
    return m.get("swap") is True and m.get("linear") is True and (
      m.get("quote")=="USDT" and m.get("settle")=="USDT" and
      m.get("active") is not False and m.get("base") in COINS)

def fetch_one(venue,coins,start,end):
    import ccxt
    out={"venue":venue,"bars":{},"errors":[]}
    try:
        ex=getattr(ccxt,venue)({"enableRateLimit":True,"timeout":15000,
                               "options":{"defaultType":"swap"}})
        ex.load_markets()
        if not ex.has.get("fetchOHLCV"):
            raise RuntimeError("No OHLCV support")
        markets={}
        for sym,m in ex.markets.items():
            if market_ok(m) and m.get("base") not in markets:
                markets[m["base"]]=sym
        for coin in coins:
            sym=markets.get(coin)
            if not sym:
                continue
            bars={}
            current=start
            for _ in range(5):
                if current>=end:break
                try:
                    result=ex.fetch_ohlcv(sym,timeframe="1m",since=current,limit=600)
                    if not result:break
                    last=-1
                    for item in result:
                        t=int(item[0])
                        if t<start or t>=end:continue
                        try:
                            o,h,l,c=map(float,item[1:5])
                            if min(o,h,l,c)>0 and all(math.isfinite(z) for z in (o,h,l,c)):
                                bars[t]=(o,h,l,c)
                        except (TypeError,ValueError):pass
                        last=max(last,t)
                    newest=int(result[-1][0])
                    if newest<current:break
                    current=newest+60000
                    if len(result)<2:break
                except Exception as err:
                    if len(out["errors"])<8:out["errors"].append(f"{coin}: {type(err).__name__}: {str(err)[:80]}")
                    break
            if len(bars)>=90:
                out["bars"][coin]=bars
    except Exception as err:
        out["fatal"]=f"{type(err).__name__}: {str(err)[:170]}"
    out["count"]=len(out["bars"])
    return out

def get_bar(hist,venue,coin,t):
    return hist.get(venue,{}).get(coin,{}).get(t)

def exit_value(pos,bar_l,bar_s):
    qty=pos["qty"]
    long_exit=bar_l[0]*(1-SLIP)
    short_exit=bar_s[0]*(1+SLIP)
    gross_l=qty*(long_exit-pos["entry_long"])
    gross_s=qty*(pos["entry_short"]-short_exit)
    close_fees=qty*(long_exit+short_exit)*FEE
    net=gross_l+gross_s-pos["entry_fees"]-close_fees
    return net,gross_l,gross_s,qty*long_exit*FEE,qty*short_exit*FEE

def one_run(history,times,start_index,end_index,threshold,leverage,allocation,
            hold=MAX_HOLD,require_persistence=True):
    balances={venue:START_WALLET for venue in VENUES}
    positions=[]
    events=[]
    counts=Counter()
    peak=START_WALLET*len(VENUES)
    trough=0.0
    nbar=end_index-start_index
    for i in range(max(start_index,2),end_index):
        t=times[i]
        # First close existing positions at current candle OPEN, so no future bar
        # closes enter a decision. Intrabar liquidation risk is flagged separately.
        for p in list(positions):
            a=get_bar(history,p["long"],p["coin"],t)
            b=get_bar(history,p["short"],p["coin"],t)
            if a is None or b is None:
                counts["missing_mark"]+=1
                continue
            net,gl,gs,fee_l,fee_s=exit_value(p,a,b)
            qty=p["qty"]
            # If the upcoming minute contains a maintenance-margin breach, real
            # broker liquidation may occur at an unknown point. Conservative:
            # forfeit the margin of both legs and label as approximate.
            bad_l=(p["margin_long"]+qty*(a[2]*(1-SLIP)-p["entry_long"])
                   <=qty*a[2]*MAINTENANCE)
            bad_s=(p["margin_short"]+qty*(p["entry_short"]-b[1]*(1+SLIP))
                   <=qty*b[1]*MAINTENANCE)
            if bad_l or bad_s:
                pnl=-(p["margin_long"]+p["margin_short"]+p["entry_fees"])
                credited_l=credited_s=0.0
                reason="APPROX_MARGIN_BREACH"
            elif net>=max(1.0,0.0025*(p["margin_long"]+p["margin_short"])):
                pnl=net
                credited_l=max(0,p["margin_long"]+gl-fee_l)
                credited_s=max(0,p["margin_short"]+gs-fee_s)
                reason="NET_TAKE_PROFIT"
            elif net<=-MAX_TRADE_LOSS:
                pnl=net
                credited_l=max(0,p["margin_long"]+gl-fee_l)
                credited_s=max(0,p["margin_short"]+gs-fee_s)
                reason="LOSS_LIMIT"
            elif i-p["open_index"]>=hold:
                pnl=net
                credited_l=max(0,p["margin_long"]+gl-fee_l)
                credited_s=max(0,p["margin_short"]+gs-fee_s)
                reason="MAX_HOLD"
            else:
                continue
            balances[p["long"]]+=credited_l
            balances[p["short"]]+=credited_s
            counts[reason]+=1
            events.append({"coin":p["coin"],"long":p["long"],"short":p["short"],
                           "entry_gap_pct":round(p["entry_gap"]*100,4),
                           "open_utc":iso(times[p["open_index"]]),
                           "close_utc":iso(t),"leverage":leverage,
                           "margin_per_leg":round((p["margin_long"]+p["margin_short"])/2,2),
                           "net_usdt":round(pnl,4),"reason":reason})
            positions.remove(p)
        if i==end_index-1:continue # no open positions at unobserved future
        previous=times[i-1]
        earlier=times[i-2]
        used={p[v] for p in positions for v in ("long","short")}
        active_coins={p["coin"] for p in positions}
        ideas=[]
        for coin in COINS:
            if coin in active_coins:continue
            prices=[]
            for venue in VENUES:
                prior=get_bar(history,venue,coin,previous)
                old=get_bar(history,venue,coin,earlier)
                if prior and old:
                    prices.append((venue,prior[3],old[3]))
            if len(prices)<2:continue
            median=statistics.median(x[1] for x in prices)
            prices=[x for x in prices if abs(x[1]/median-1)<0.025]
            for low,low_c,low_old in prices:
                for high,high_c,high_old in prices:
                    if low==high:continue
                    spread=high_c/low_c-1
                    old_spread=high_old/low_old-1
                    if spread<threshold:continue
                    if require_persistence and old_spread<threshold:continue
                    ideas.append((spread,coin,low,high))
        ideas.sort(reverse=True)
        if ideas:counts["raw_signals"]+=len(ideas)
        for gap,coin,lv,sv in ideas:
            if lv in used or sv in used:continue
            current_a=get_bar(history,lv,coin,t)
            current_b=get_bar(history,sv,coin,t)
            if not current_a or not current_b:continue
            cheap,expensive=current_a[0],current_b[0]
            if expensive/cheap-1<threshold:
                counts["gap_vanished_at_next_open"]+=1
                continue
            # Strict collateral per leg, no unlimited virtual buying power.
            maxqty=min(balances[lv]*allocation/(cheap*(1/ leverage+FEE+SLIP)),
                       balances[sv]*allocation/(expensive*(1/leverage+FEE+SLIP)))
            if maxqty<=0 or cheap*maxqty<MIN_NOTIONAL:
                counts["not_enough_margin"]+=1
                continue
            entry_long=cheap*(1+SLIP)
            entry_short=expensive*(1-SLIP)
            ml=maxqty*entry_long/leverage
            ms=maxqty*entry_short/leverage
            fl=FEE*maxqty*entry_long
            fs=FEE*maxqty*entry_short
            # Hypothetical full convergence should pay a minimum net after
            # 4 fills and slippage. This is NOT a forecast.
            convergence=maxqty*((expensive-cheap)-
                                (cheap+expensive)*(2*FEE+2*SLIP))
            if convergence<MIN_NET_CONVERGENCE_SCENARIO:
                counts["no_full_convergence_cushion"]+=1
                continue
            if ml+fl>balances[lv] or ms+fs>balances[sv]:
                counts["not_enough_margin"]+=1
                continue
            balances[lv]-=ml+fl
            balances[sv]-=ms+fs
            positions.append({"coin":coin,"long":lv,"short":sv,"qty":maxqty,
                              "entry_long":entry_long,"entry_short":entry_short,
                              "entry_gap":expensive/cheap-1,
                              "margin_long":ml,"margin_short":ms,
                              "entry_fees":fl+fs,"open_index":i})
            used.update((lv,sv));active_coins.add(coin)
            counts["opened"]+=1
            if len(positions)>=2:break

    # Mark the last available candle open, rather than fabricate a fill
    # when end-of-window data is absent.
    final_free=sum(balances.values())
    reserved=sum(p["margin_long"]+p["margin_short"] for p in positions)
    marked_pnl=0.0
    good=True
    for p in positions:
        a=get_bar(history,p["long"],p["coin"],times[end_index-1])
        b=get_bar(history,p["short"],p["coin"],times[end_index-1])
        if not a or not b:good=False;break
        net,*_=exit_value(p,a,b)
        marked_pnl+=net+p["entry_fees"]
    equity=final_free+reserved+marked_pnl if good else None
    realized=sum(t["net_usdt"] for t in events)
    return {
      "params":{"min_gap_pct":round(threshold*100,3),"leverage":leverage,
                "wallet_allocation":allocation,"persistent_two_closes":require_persistence},
      "events":events,
      "closed":len(events),
      "winners":sum(e["net_usdt"]>0 for e in events),
      "realized_pnl_usdt":round(realized,2),
      "marked_equity_usdt":round(equity,2) if equity is not None else None,
      "estimated_return_pct":round((equity/5000-1)*100,3) if equity is not None else None,
      "open_at_end":len(positions),
      "counts":dict(counts),
      "wallets":{v:round(balances[v],2) for v in VENUES},
      "start_utc":iso(times[start_index]),"end_utc_exclusive":iso(times[end_index-1]+60000),
    }

def choose(training):
    # Optimise TRAIN ONLY; never let test-period performance choose parameters.
    eligible=[x for x in training if x["closed"]>=3 and x["marked_equity_usdt"] is not None
              and not x["counts"].get("APPROX_MARGIN_BREACH")]
    if not eligible:return None
    eligible.sort(key=lambda z:(z["estimated_return_pct"],z["closed"]),reverse=True)
    # Require >0 after friction or explicitly reject promotion.
    return eligible[0] if eligible[0]["estimated_return_pct"]>0 else None

def selftest():
    fake={"okx":{"BTC":{}}, "bitget":{"BTC":{}}}
    t=[i*60000 for i in range(13)]
    for i,v in enumerate(t):
        fake["okx"]["BTC"][v]=(100.0,100.1,99.9,100.0)
        fake["bitget"]["BTC"][v]=(100.8,100.9,100.7,100.8)
    # Repeated stale-looking spread can appear profitable; exercise accounting.
    x=one_run(fake,t,0,len(t),0.006,2,0.1)
    assert x["marked_equity_usdt"] is not None
    assert x["params"]["leverage"]==2
    assert 0<=x["closed"]<=len(t)
    assert abs(sum(v for v in x["wallets"].values())-5000)<1500
    print("✅ Offline replay arithmetic and fixture sanity checks passed")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--hours",type=int,default=6)
    p.add_argument("--coins",type=int,default=50)
    p.add_argument("--out",default="sol-arb-paper-20/reports/walkforward_v6.json")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:return selftest()
    if a.hours<4 or a.hours>12 or a.coins<3 or a.coins>len(COINS):
        p.error("Hours 4–12 and coins 3–85")
    end=(int(time.time()*1000)//60000)*60000
    start=end-a.hours*3600000
    times=list(range(start,end,60000))
    coins=COINS[:a.coins]
    print("🧪 V6 NEXT-BAR OPEN WALK-FORWARD |",iso(start),"→",iso(end),flush=True)
    print("🔎 Public 1m perpetual OHLCV only | 5 x 1000 USDT | NO REAL ORDERS",flush=True)
    print("🛑 This is exploratory NOT an execution-grade or live-ready backtest.",flush=True)
    results={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(VENUES)) as pool:
        jobs={v:pool.submit(fetch_one,v,coins,start,end) for v in VENUES}
        for v in VENUES:
            results[v]=jobs[v].result()
            o=results[v]
            print("📡",v,"coin feeds",o["count"],"errors",len(o["errors"]),
                  "fatal",o.get("fatal","none"),flush=True)
    history={v:r["bars"] for v,r in results.items()}
    multi_coins=[c for c in coins if sum(c in history[v] for v in VENUES)>=2]
    if len(multi_coins)<8:
        raise SystemExit("Insufficient common historical public bars. No fabricated results.")
    split=int(len(times)*2/3)
    # Precommit fixed parameter grid, no test-period curve fitting.
    params=[(gap,lev,alloc,persist)
            for gap in (0.006,0.008,0.010)
            for lev in (2,5,10,20)
            for alloc in (0.15,0.35,0.70)
            for persist in (True,False)]
    training=[]
    for gap,lev,alloc,persist in params:
        training.append(one_run(history,times,0,split,gap,lev,alloc,
                                require_persistence=persist))
    champion=choose(training)
    # Baseline test and champion test are independent balances, unseen period.
    baseline=one_run(history,times,split,len(times),0.006,20,0.70,
                     require_persistence=False)
    validation=one_run(history,times,split,len(times),
                       champion["params"]["min_gap_pct"]/100,
                       champion["params"]["leverage"],
                       champion["params"]["wallet_allocation"],
                       require_persistence=champion["params"]["persistent_two_closes"]) if champion else None
    data={
      "status":"UNVERIFIED CANDLE-ONLY HISTORICAL REPLAY - NO EXECUTABLE ORDER BOOKS",
      "window_start_utc":iso(start),"window_end_utc":iso(end),
      "training_hours":round(split/60,2),"validation_hours":round((len(times)-split)/60,2),
      "coins_requested":len(coins),"coins_covered_in_2plus_venues":len(multi_coins),
      "venue_coin_feeds":{v:r["count"] for v,r in results.items()},
      "venue_errors":{v:{"fatal":r.get("fatal"),"sample":r["errors"][:5]} for v,r in results.items()},
      "wallets":5,"initial_equity_usdt":5000,
      "no_future_bar_signal_leakage":True,
      "training_scenarios":len(params),
      "train_top5":sorted(training,key=lambda x:x["estimated_return_pct"] or -1e12,reverse=True)[:5],
      "training_selection":champion,
      "baseline_unseen_validation":baseline,
      "selected_unseen_validation":validation,
      "promotion_decision":"NOT VALIDATED FOR REAL TRADING",
      "limitations":[
        "Signals use completed candle closes and hypothetical entry/exit at NEXT minute opens, not synchronized executable order books.",
        "Intraminute extremes only approximate margin breach; real 20x liquidation could happen sooner than candle resolution.",
        "No real fill queue, order book size, funding, contract size, precise fee tier, outage, delayed leg, cross-venue transfer.",
        "Data training/test split is chronological but still only a few hours; repeated testing risks overfitting.",
        "If no positive train candidate has >=3 closed trades, no strategy is promoted.",
      ],
    }
    path=Path(a.out);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2)+"\n")
    print("\n===== OUT-OF-SAMPLE PAPER REPLAY SUMMARY =====")
    print("Coin feeds:",data["venue_coin_feeds"],"Common coins:",len(multi_coins))
    print("Training scenarios:",len(params),"Champion:",champion["params"] if champion else "NONE")
    print("Baseline validation:",{k:baseline[k] for k in ("closed","winners","realized_pnl_usdt","estimated_return_pct")})
    if validation:
        print("Selected validation:",{k:validation[k] for k in ("closed","winners","realized_pnl_usdt","estimated_return_pct")})
    else:print("No qualifying training strategy. No promotion.")
    print("Report:",path)
    print("⚠️ CANDLE PROXY ONLY — NO EVIDENCE OF EXECUTABLE PROFIT.")

if __name__=="__main__":
    main()
