#!/usr/bin/env python3
"""V4 PAPER multi-coin futures spread-convergence observer with diagnostics.
30 prospective venues x 500 USDT simulated paper wallets. 100 prospective coins.
Temporary worker processes avoid retaining full exchange catalogs in 1 GB RAM.
Public market data only. No API keys; NEVER PLACES REAL ORDERS.
"""
import argparse, concurrent.futures, datetime, json, math, os, subprocess
import sys, time, statistics, random
from collections import Counter
from pathlib import Path

VENUES = [
 "binanceusdm","bybit","okx","bitget","gate","mexc",
 "kucoinfutures","bingx","htx","phemex","bitmart","coinex",
 "cryptocom","hyperliquid","woo","krakenfutures","bitfinex",
 "poloniex","xt","ascendex","aster","blofin","btse",
 "backpack","bitrue","delta","dydx","lbank","toobit","weex"
]
COINS = list(dict.fromkeys((
 "BTC ETH SOL XRP DOGE BNB ADA LINK AVAX LTC TRX DOT BCH UNI XLM ETC "
 "APT ARB OP SUI NEAR FIL ATOM ICP AAVE PEPE SHIB INJ POL TON "
 "WIF BONK FET RUNE GRT SEI TIA STX JUP ENA MKR ALGO HBAR "
 "SAND MANA CRV LDO IMX FLOKI ONDO NEO EOS DYDX GMX ZEC "
 "DASH COMP SNX KAVA LRC GALA AXS CHZ XTZ EGLD ZIL 1INCH "
 "ZRX MASK ROSE CELO MINA IOTA ENS SUSHI YFI QTUM KSM CFX "
 "WLD BLUR PYTH WOO MEME TURBO ORDI BOME NOT BRETT POPCAT "
 "PNUT PENGU VIRTUAL JASMY ZRO STRK ZK KAIA RAY FARTCOIN "
 "ETHFI SSV SUPER PENDLE OM"
).split()))[:100]
START_USDT_PER_VENUE = 500.0
FEE = 0.0006
SLIP = 0.0005
MIN_GAP = 0.007
MIN_ORDER = 25.0
MAX_ORDER_FRACTION = 0.80
MAX_OPEN = 6
TAKE_PROFIT_USDT = 0.25
TAKE_PROFIT_FRACTION = 0.001
STOP_LOSS_FRACTION = -0.02
MAX_HOLD_SECONDS = 3600
MAX_QUOTE_AGE_MS = 20000
# Ticker snapshots only generate candidate ideas. All fills require fresh books.
# A discovery window longer than 8 seconds is needed when rotating 30 venues.
MAX_DISCOVERY_AGE_SECONDS = 90.0
BOOK_RECHECK_BACKOFF_SECONDS = 25.0
MAX_VALIDATIONS_PER_BATCH = 3
MAX_BOOK_SKEW_SECONDS = 3.0
STATE_VERSION = 4

def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def num(x):
    try:
        v=float(x)
        return v if math.isfinite(v) and v>0 else None
    except (ValueError, TypeError):
        return None

def market_filter(m):
    return (
        m.get("swap") is True and m.get("linear") is True and
        m.get("quote") == "USDT" and m.get("settle") == "USDT" and
        m.get("active") is not False and m.get("base") in COINS
    )

def worker(venue, mode, coin=None):
    """Isolated process: CCXT markets freed by OS as soon as call finishes."""
    try:
        import ccxt
        if venue not in ccxt.exchanges:
            return {"venue":venue,"error":"CCXT ID unavailable"}
        ex=getattr(ccxt,venue)({
            "enableRateLimit":True, "timeout":12000,
            "options":{"defaultType":"swap"},
        })
        markets=ex.load_markets()
        eligible={}
        for symbol,meta in markets.items():
            if market_filter(meta) and meta["base"] not in eligible:
                eligible[meta["base"]]=(symbol,meta)
        if mode == "tickers":
            if not eligible or not ex.has.get("fetchTickers"):
                return {"venue":venue,"error":"No supported USDT perps / ticker endpoint"}
            try:
                data=ex.fetch_tickers([v[0] for v in eligible.values()])
            except Exception:
                # Only try unfiltered tickers if symbol-scoped batch is not supported.
                data=ex.fetch_tickers()
            got=time.monotonic()
            quotes={}
            for base,(symbol,meta) in eligible.items():
                t=data.get(symbol)
                if not isinstance(t,dict):continue
                bid,ask=num(t.get("bid")),num(t.get("ask"))
                if not bid or not ask or bid>=ask:continue
                ts=t.get("timestamp")
                if ts is not None:
                    try:
                        age=time.time()*1000-float(ts)
                        if age>MAX_QUOTE_AGE_MS or age < -20000:continue
                    except (ValueError,TypeError):continue
                vol=t.get("quoteVolume")
                if vol is not None:
                    try:
                        if 0<float(vol)<2000000:continue
                    except (ValueError, TypeError):pass
                quotes[base]=[bid,ask]
            return {"venue":venue,"at":got,"coins_supported":len(eligible),"quotes":quotes}
        if mode == "book":
            if coin not in eligible or not ex.has.get("fetchOrderBook"):
                return {"venue":venue,"error":"No compatible book for "+str(coin)}
            sym,meta=eligible[coin]
            contract_size=num(meta.get("contractSize")) or 1.0
            # CCXT contract books may report contract quantities rather than base units.
            book=ex.fetch_order_book(sym,limit=20)
            at=time.monotonic()
            def normalize(raw,reverse=False):
                rows=[]
                for price,amount in raw:
                    p,q=num(price),num(amount)
                    if p and q:rows.append([p,q*contract_size])
                rows.sort(key=lambda x:x[0],reverse=reverse)
                return rows
            bids,asks=normalize(book.get("bids",[]),True),normalize(book.get("asks",[]),False)
            if not bids or not asks or bids[0][0]>=asks[0][0]:
                return {"venue":venue,"error":"Invalid book"}
            ts=book.get("timestamp")
            if ts is not None:
                age=time.time()*1000-float(ts)
                if age>MAX_QUOTE_AGE_MS or age< -20000:
                    return {"venue":venue,"error":"Stale exchange book"}
            return {"venue":venue,"at":at,"bids":bids,"asks":asks,"coin":coin,
                    "contract_size":contract_size}
        return {"venue":venue,"error":"Unsupported worker mode"}
    except Exception as ex:
        return {"venue":venue,"error":type(ex).__name__+": "+str(ex)[:115]}

def call_worker(venue,mode,coin=None,timeout=32):
    cmd=[sys.executable,os.path.abspath(__file__),"--worker",venue,mode]
    if coin:cmd.append(coin)
    try:
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=timeout,check=False)
        if p.returncode:
            return {"venue":venue,"error":"worker returned "+str(p.returncode)+": "+p.stderr[-100:]}
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (OSError,ValueError,subprocess.TimeoutExpired) as ex:
        return {"venue":venue,"error":type(ex).__name__}

def pair_books(left,right,coin,pool):
    tasks=[pool.submit(call_worker,venue,"book",coin) for venue in (left,right)]
    books=[task.result() for task in tasks]
    if any("error" in x for x in books):return None
    if abs(books[0]["at"]-books[1]["at"])>MAX_BOOK_SKEW_SECONDS:return None
    return books

def vwap(rows,quantity):
    remains=quantity
    cost=0
    for price,amount in rows:
        amount=min(amount,remains)
        remains-=amount
        cost+=amount*price
        if remains<=1e-9:return cost/quantity
    return None

def evaluate_close(pos,lb,sb):
    qty=pos["qty"]
    raw_sell=vwap(lb["bids"],qty)
    raw_buy=vwap(sb["asks"],qty)
    if not raw_sell or not raw_buy:return None
    long_exit=raw_sell*(1-SLIP)
    short_exit=raw_buy*(1+SLIP)
    long_gross=qty*(long_exit-pos["long_entry"])
    short_gross=qty*(pos["short_entry"]-short_exit)
    close_fees=qty*(long_exit+short_exit)*FEE
    net=long_gross+short_gross-pos["open_fees"]-close_fees
    return dict(net=net,long_gross=long_gross,short_gross=short_gross,
                close_long_fee=qty*long_exit*FEE,
                close_short_fee=qty*short_exit*FEE)

def new_state():
    return {
      "version":STATE_VERSION,"created_utc":stamp(),
      "wallets":{name:START_USDT_PER_VENUE for name in VENUES},
      "positions":[],"completed_pairs":0,"realized_net_pnl_usdt":0.0,
      "scan_batches":0,"connected":{},"errors":{},
      "diagnostics":{},"top_discrepancies":[],"candidate_total":0,
    }

def atomic_json(path,obj):
    temp=path.with_suffix(".tmp")
    temp.write_text(json.dumps(obj,indent=2)+"\n")
    os.replace(temp,path)

def load_state(path):
    if not path.exists():return new_state()
    data=json.loads(path.read_text())
    if data.get("version")!=STATE_VERSION or set(data.get("wallets",{}))!=set(VENUES):
        raise ValueError("Existing state incompatible. Do not overwrite without preserving it.")
    return data

def append_event(path,obj):
    with path.open("a") as f:
        f.write(json.dumps(obj,separators=(",",":"))+"\n")

def summary(state,unrealized=None):
    positions=state["positions"]
    free=sum(state["wallets"].values())
    margin=sum(p["long_margin"]+p["short_margin"] for p in positions)
    # Opening fees are already charged to wallet cash.
    equity=(free+margin+unrealized+sum(p['open_fees'] for p in positions)) if unrealized is not None else None
    supported=[name for name,x in state["connected"].items() if x.get("quotes",0)>0]
    result={
      "utc":stamp(),"starting_equity_usdt":len(VENUES)*START_USDT_PER_VENUE,
      "starting_per_exchange_usdt":START_USDT_PER_VENUE,
      "configured_exchanges":len(VENUES),"supported_exchanges":sorted(supported),
      "funded_wallets":{x:round(state["wallets"][x],4) for x in VENUES},
      "instrument_universe":len(COINS),"scan_batches":state["scan_batches"],
      "open_pairs":len(positions),"completed_pairs":state["completed_pairs"],
      "open_position_details":[{"coin":p["coin"],"long":p["long"],"short":p["short"],
        "notional_usdt":round(p["notional"],3)} for p in positions],
      "realized_net_pnl_usdt":round(state["realized_net_pnl_usdt"],4),
      "unrealized_net_pnl_usdt":round(unrealized,4) if unrealized is not None else None,
      "wallet_free_usdt":round(free,4),
      "reserved_margin_usdt":round(margin,4),
      "estimated_equity_usdt":round(equity,4) if equity is not None else None,
      "exchange_errors":state["errors"],
      "exchange_status":state["connected"],
      "candidate_total":state.get("candidate_total",0),
      "diagnostics":state.get("diagnostics",{}),
      "top_discrepancies":state.get("top_discrepancies",[]),
      "elapsed_minutes":round(state.get("elapsed_seconds",0)/60,2),
      "warning":"PAPER-ONLY ESTIMATE. 30 $500 simulated allocations include inactive venues. "
        "30 exchanges are sampled in rotating small batches, NOT all at once. "
        "Stale ticker quotes rank possible routes only. New books are fetched before a hypothetical fill. "
        "Feed connectivity and snapshot availability may not imply actual exchange access. "
        "Funding, liquidation mechanics, borrowing, taxes, exchange access and venue-specific fees are not fully modeled."
    }
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--minutes",type=float,default=60)
    parser.add_argument("--workers",type=int,default=2)
    parser.add_argument("--poll",type=float,default=5)
    parser.add_argument("--output",default="/root/sol-arb-paper-20-aggressive/multicoin-v3")
    args=parser.parse_args()
    if args.minutes<=0 or args.workers not in (1,2) or args.poll<2:
        parser.error("minutes>0, workers must be 1 or 2, poll>=2")
    root=Path(args.output);root.mkdir(parents=True,exist_ok=True)
    state_path=root/"state.json"
    state=load_state(state_path)
    logs=root/"events.jsonl"
    qcache={}
    next_index=0
    active_since=time.monotonic()
    last_verified={}
    print("🚀 MULTICOIN V4 PAPER ONLY | 30 VENUE WALLETS x $500 = $15,000 | 100 COINS",flush=True)
    print("🛑 NO REAL ORDERS | rotating 2-venue batches | longer DISCOVERY cache, fresh books required",flush=True)
    print("🔎 Diagnostics enabled: top observed gaps, rejected book checks, completed pairs",flush=True)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            while time.monotonic()-active_since<args.minutes*60:
                tick=time.monotonic()
                # Exit monitoring is higher priority than searching for new spreads.
                unpriced=[]
                unrealized=0.0
                priced=set()
                for p in list(state["positions"]):
                    if time.monotonic()-tick>35:break
                    books=pair_books(p["long"],p["short"],p["coin"],pool)
                    if books is None:
                        unpriced.append(p["coin"])
                        continue
                    result=evaluate_close(p,*books)
                    if result is None:
                        unpriced.append(p["coin"])
                        continue
                    hold=time.time()-p["opened_unix"]
                    net=result["net"]
                    should_close=(
                       (hold>=20 and net>=max(TAKE_PROFIT_USDT,p["notional"]*TAKE_PROFIT_FRACTION)) or
                       net <= STOP_LOSS_FRACTION*p["notional"] or
                       hold>=MAX_HOLD_SECONDS
                    )
                    if should_close:
                        long_credit=p["long_margin"]+result["long_gross"]-result["close_long_fee"]
                        short_credit=p["short_margin"]+result["short_gross"]-result["close_short_fee"]
                        state["wallets"][p["long"]]+=long_credit
                        state["wallets"][p["short"]]+=short_credit
                        state["realized_net_pnl_usdt"]+=net
                        state["completed_pairs"]+=1
                        state["positions"].remove(p)
                        append_event(logs,{"event":"CLOSE","utc":stamp(),"coin":p["coin"],
                            "long":p["long"],"short":p["short"],"net_realized_pnl_usdt":round(net,4),
                            "held_seconds":round(hold)})
                        print("✅ CLOSE",p["coin"],round(net,3),"USDT",flush=True)
                    else:
                        unrealized+=net
                        priced.add((p['long'],p['short'],p['coin']))
                # Two tickers in parallel: a frequent anchor and a rotating venue.
                # This increases useful comparisons while keeping only two workers.
                anchors=("binanceusdm","bybit","okx","bitget")
                anchor=anchors[state["scan_batches"]%len(anchors)]
                other=VENUES[next_index%len(VENUES)]
                next_index+=1
                if other==anchor:
                    other=VENUES[next_index%len(VENUES)]
                    next_index+=1
                batch=[anchor,other]
                jobs=[pool.submit(call_worker,v,"tickers") for v in batch]
                results=[j.result() for j in jobs]
                now=time.monotonic()
                for r in results:
                    name=r["venue"]
                    if "error" in r:
                        state["errors"][name]=r["error"]
                        continue
                    state["connected"][name]={"coins":r.get("coins_supported",0),
                                               "quotes":len(r.get("quotes",{})),
                                               "last_seen_utc":stamp()}
                    qcache[name]=r
                # Candidate DISCOVERY may inspect a bounded recent quote cache.
                # NEVER count this as execution: both books must be freshly checked.
                qcache={name:q for name,q in qcache.items()
                        if now-q["at"]<=MAX_DISCOVERY_AGE_SECONDS}
                state["cache_venues"]=len(qcache)
                open_coins={p["coin"] for p in state["positions"]}
                bycoin={}
                for name,q in qcache.items():
                    for coin,bid_ask in q["quotes"].items():
                        if coin not in open_coins:
                            bycoin.setdefault(coin,[]).append((name,bid_ask,q["at"]))
                candidates=[]
                observed=[]
                compared=0
                for coin,prices in bycoin.items():
                    if len(prices)<2:continue
                    median=statistics.median([(bid+ask)/2 for _,(bid,ask),_ in prices])
                    prices=[(name,quote,t) for name,quote,t in prices
                            if abs((quote[0]+quote[1])/2/median-1)<0.12]
                    for buy,(bid,ask),bt in prices:
                        if len(prices)<2:continue
                        for sell,(sbid,sask),st in prices:
                            if sell==buy:continue
                            compared+=1
                            gap=sbid/ask-1
                            if gap>0:
                                observed.append((gap,coin,buy,sell,round(abs(bt-st),1)))
                            if gap>=MIN_GAP:
                                candidates.append((gap,coin,buy,sell))
                observed.sort(reverse=True)
                state["top_discrepancies"]=[
                    {"coin":coin,"buy":buy,"sell":sell,
                     "gross_gap_pct":round(gap*100,3),"quote_skew_s":skew,
                     "status":"DISCOVERY ONLY — not executable until fresh books"}
                    for gap,coin,buy,sell,skew in observed[:10]
                ]
                state["candidate_total"]+=len(candidates)
                d=state["diagnostics"]
                d["pairs_compared"]=d.get("pairs_compared",0)+compared
                d["positive_spreads"]=d.get("positive_spreads",0)+len(observed)
                d["spreads_above_entry_threshold"]=d.get("spreads_above_entry_threshold",0)+len(candidates)
                if not candidates:
                    d["batches_no_candidate"]=d.get("batches_no_candidate",0)+1
                candidates.sort(reverse=True)
                checked=0
                for gap,coin,buy,sell in candidates:
                    if len(state["positions"])>=MAX_OPEN:
                        d["position_capacity_reached"]=d.get("position_capacity_reached",0)+1
                        break
                    if checked>=MAX_VALIDATIONS_PER_BATCH:break
                    if coin in {p["coin"] for p in state["positions"]}:continue
                    route=(buy,sell,coin)
                    if now-last_verified.get(route,-1e9)<BOOK_RECHECK_BACKOFF_SECONDS:
                        continue
                    last_verified[route]=now
                    checked+=1
                    books=pair_books(buy,sell,coin,pool)
                    if books is None:
                        d["book_unavailable_or_skewed"]=d.get("book_unavailable_or_skewed",0)+1
                        continue
                    lb,sb=books
                    live_gap=sb["bids"][0][0]/lb["asks"][0][0]-1
                    if live_gap<MIN_GAP:
                        d["gap_disappeared_at_book"]=d.get("gap_disappeared_at_book",0)+1
                        continue
                    strength=min(MAX_ORDER_FRACTION,0.25+(live_gap-MIN_GAP)*20)
                    # At 1x notional, both legs must be fully collateralized.
                    left_capacity=state["wallets"][buy]*strength/(1+FEE)
                    right_capacity=state["wallets"][sell]*strength/(1+FEE)
                    max_depth=min(sum(q for p,q in lb["asks"]),sum(q for p,q in sb["bids"]))*0.75
                    qty=min(left_capacity/lb["asks"][0][0],
                            right_capacity/sb["bids"][0][0],max_depth)
                    if qty<=0:
                        d["no_margin_or_depth"]=d.get("no_margin_or_depth",0)+1
                        continue
                    bp=vwap(lb["asks"],qty)
                    sp=vwap(sb["bids"],qty)
                    if bp is None or sp is None:
                        d["insufficient_book_depth"]=d.get("insufficient_book_depth",0)+1
                        continue
                    long_entry=bp*(1+SLIP)
                    short_entry=sp*(1-SLIP)
                    net_gap=short_entry/long_entry-1
                    if net_gap<4*FEE+2*SLIP+TAKE_PROFIT_FRACTION:
                        d["after_fees_or_slippage"]=d.get("after_fees_or_slippage",0)+1
                        continue
                    long_margin=qty*long_entry
                    short_margin=qty*short_entry
                    open_long_fee=long_margin*FEE
                    open_short_fee=short_margin*FEE
                    if min(long_margin,short_margin)<MIN_ORDER:
                        d["below_minimum_notional"]=d.get("below_minimum_notional",0)+1
                        continue
                    if state["wallets"][buy]<long_margin+open_long_fee or state["wallets"][sell]<short_margin+open_short_fee:
                        d["venue_wallet_insufficient"]=d.get("venue_wallet_insufficient",0)+1
                        continue
                    state["wallets"][buy]-=long_margin+open_long_fee
                    state["wallets"][sell]-=short_margin+open_short_fee
                    pos={"coin":coin,"long":buy,"short":sell,"qty":qty,
                         "long_entry":long_entry,"short_entry":short_entry,
                         "long_margin":long_margin,"short_margin":short_margin,
                         "open_fees":open_long_fee+open_short_fee,
                         "notional":long_margin,"opened_unix":time.time()}
                    state["positions"].append(pos)
                    d["paper_pairs_opened"]=d.get("paper_pairs_opened",0)+1
                    append_event(logs,{"event":"OPEN","utc":stamp(),"coin":coin,
                        "long":buy,"short":sell,"qty":qty,
                        "verified_gap_pct":round(live_gap*100,4),
                        "notional_usdt":round(long_margin,3),
                        "sizing_fraction":round(strength,3)})
                    print("🟢 OPEN",coin,buy,"LONG",sell,"SHORT",
                          "notional",round(long_margin,2),"gap%",round(live_gap*100,3),flush=True)
                state["scan_batches"]+=1
                state["elapsed_seconds"]=time.monotonic()-active_since
                d["last_cache_venues"]=len(qcache)
                d["last_candidates"]=len(candidates)
                d["last_books_validated"]=checked
                # Open PnL only available when every remaining position was marked.
                open_mark=(unrealized if not unpriced and len(priced)==len(state['positions']) else None)
                data=summary(state,open_mark)
                atomic_json(root/"summary.json",data)
                atomic_json(state_path,state)
                if state["scan_batches"]%3==0:
                    top=state.get("top_discrepancies",[])
                    print("📊 BATCH",state["scan_batches"],
                      "venues seen",len(state["connected"]),
                      "cached",len(qcache),"candidates",len(candidates),
                      "books checked",checked,"top gap",top[0] if top else "none",
                      "open",len(state["positions"]),
                      "closed",state["completed_pairs"],
                      "realized",round(state["realized_net_pnl_usdt"],4),flush=True)
                time.sleep(max(0,args.poll-(time.monotonic()-tick)))
    except KeyboardInterrupt:
        print("🛑 Ctrl+C: saving state. Real orders were never enabled.",flush=True)
    finally:
        state["elapsed_seconds"]=time.monotonic()-active_since
        atomic_json(state_path,state)
        final=summary(state,None)
        atomic_json(root/"summary.json",final)
        append_event(logs,{"event":"FINAL","summary":final})
        print("FINAL",json.dumps(final),flush=True)

if __name__=="__main__":
    if len(sys.argv)>=4 and sys.argv[1]=="--worker":
        venue,mode=sys.argv[2],sys.argv[3]
        coin=sys.argv[4] if len(sys.argv)>4 else None
        print(json.dumps(worker(venue,mode,coin),separators=(",",":")))
    else:main()
