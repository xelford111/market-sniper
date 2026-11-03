#!/usr/bin/env python3
"""Multi-coin cross-exchange perpetual spread convergence: PAPER ONLY.
No API keys, no real orders. Ticker discovery is NOT proof of executable arbitrage.
Public order books validate each proposed entry/exit. Funded paper wallets: 10 x $500.
"""
import argparse
import concurrent.futures as futures
import datetime as datetime
import json
import math
import os
import resource
import statistics
import time
from collections import Counter
from pathlib import Path

import ccxt

VENUE_IDS = [
    "binanceusdm", "bybit", "okx", "bitget", "gateio",
    "mexc", "kucoinfutures", "bingx", "htx", "phemex",
    "bitmart", "coinex", "cryptocom", "hyperliquid", "woo",
    "krakenfutures", "bitfinex", "poloniex", "xt", "ascendex",
]
FUNDED = VENUE_IDS[:10]
COINS = [
    "BTC","ETH","SOL","XRP","DOGE","BNB","ADA","LINK","AVAX","LTC",
    "TRX","DOT","BCH","UNI","XLM","ETC","APT","ARB","OP","SUI",
    "NEAR","FIL","ATOM","ICP","AAVE","PEPE","SHIB","INJ","POL","TON",
    "WIF","BONK","FET","RUNE","GRT","SEI","TIA","STX","JUP","ENA",
    "MKR","ALGO","HBAR","SAND","MANA","CRV","LDO","IMX","FLOKI","ONDO",
]
# Assumptions: fees and slippage EACH side, EACH fill. Four fills per round trip.
TAKER_FEE = 0.0006
SLIPPAGE = 0.0005
MIN_ENTRY_GAP = 0.007
MIN_NOTIONAL = 25.0
MAX_SHARE = 0.85
EXIT_PROFIT_FRACTION = 0.001
STOP_LOSS_FRACTION = -0.02
MAX_HOLD_SECONDS = 1800
MAX_OPEN_PAIRS = 4
MAX_MEMORY_KIB = 480000

def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def record(f, obj):
    f.write(json.dumps(obj, separators=(",",":")) + "\n")

def fresh_price(price):
    try:
        x = float(price)
        return x if math.isfinite(x) and x > 0 else None
    except (TypeError, ValueError):
        return None

def is_perp(market):
    return (market.get("swap") is True and market.get("linear") is True
            and market.get("quote") == "USDT" and market.get("settle") == "USDT"
            and market.get("active") is not False)

def setup_venue(exchange_id):
    ex = getattr(ccxt, exchange_id)({
        "enableRateLimit": True,
        "timeout": 8000,
        "options": {"defaultType":"swap"},
    })
    ex.load_markets()
    markets={}
    for symbol, m in ex.markets.items():
        if is_perp(m) and m.get("base") in COINS:
            base=m["base"]
            if base not in markets:
                markets[base]=symbol
    if not markets or not ex.has.get("fetchTickers") or not ex.has.get("fetchOrderBook"):
        return None, 0, "no compatible USDT perps or ticker/depth endpoint"
    return (ex,markets),len(markets),None

def fetch_tickers(info):
    name, (ex, market_symbols) = info
    received=time.monotonic()
    try:
        requested=list(market_symbols.values())
        # CCXT rate-limits both requests; some venues reject symbol filters.
        try:
            raw=ex.fetch_tickers(requested)
        except Exception:
            raw=ex.fetch_tickers()
        received=time.monotonic()
        quotes={}
        for coin,symbol in market_symbols.items():
            t=raw.get(symbol)
            if not t: continue
            bid,ask=fresh_price(t.get("bid")),fresh_price(t.get("ask"))
            if not bid or not ask or bid>=ask:continue
            volume=t.get("quoteVolume")
            # If 24h quote volume is supplied, reject obviously illiquid contracts.
            if volume is not None:
                try:
                    if float(volume)>0 and float(volume)<2000000:continue
                except (ValueError,TypeError):pass
            timestamp=t.get("timestamp")
            if timestamp:
                try:
                    age=time.time()*1000-float(timestamp)
                    if age>60000 or age< -20000:continue
                except (ValueError,TypeError):pass
            quotes[coin]={"bid":bid,"ask":ask,"received":received}
        return name,quotes,None
    except Exception as error:
        return name,{},type(error).__name__+": "+str(error)[:100]

def depth(name,coin,venues):
    ex, symbols=venues[name]
    try:
        book=ex.fetch_order_book(symbols[coin],limit=20)
        received=time.monotonic()
        bids=[(float(p),float(q)) for p,q in book["bids"] if float(p)>0 and float(q)>0]
        asks=[(float(p),float(q)) for p,q in book["asks"] if float(p)>0 and float(q)>0]
        if not bids or not asks or bids[0][0]>=asks[0][0]:
            raise ValueError("invalid or crossed book")
        return {"name":name,"coin":coin,"bids":bids,"asks":asks,"at":received}
    except Exception as error:
        return {"name":name,"coin":coin,"error":type(error).__name__+": "+str(error)[:90]}

def books_pair(buy,sell,coin,venues,pool):
    a=pool.submit(depth,buy,coin,venues)
    b=pool.submit(depth,sell,coin,venues)
    left,right=a.result(),b.result()
    if "error" in left or "error" in right: return None
    if abs(left["at"]-right["at"])>2.0: return None
    return left,right

def available_amount(levels):
    return sum(q for p,q in levels)

def vwap(levels,quantity):
    amount_left=quantity
    cost=0
    for p,qty in levels:
        n=min(qty,amount_left)
        cost+=n*p;amount_left-=n
        if amount_left<=1e-10:return cost/quantity
    return None

def hypothetical_close(position,left,right):
    """Net profit including 4 fees, 4 adverse slippage adjustments."""
    qty=position["qty"]
    long_exit=vwap(left["bids"],qty)
    short_exit=vwap(right["asks"],qty)
    if not long_exit or not short_exit:return None
    long_exit=long_exit*(1-SLIPPAGE)
    short_exit=short_exit*(1+SLIPPAGE)
    long_pnl=(long_exit-position["long_entry"])*qty
    short_pnl=(position["short_entry"]-short_exit)*qty
    exit_fee=(long_exit+short_exit)*qty*TAKER_FEE
    net=long_pnl+short_pnl-position["open_fees"]-exit_fee
    return net,long_pnl,short_pnl,exit_fee,long_exit,short_exit

def rank_routes(quotes,open_coins,venues):
    bycoin={}
    for ex,market in quotes.items():
        for coin,t in market.items():
            if coin in open_coins:continue
            bycoin.setdefault(coin,[]).append((ex,t))
    opportunities=[]
    for coin,entries in bycoin.items():
        if len(entries)<2:continue
        marks=[(t["bid"]+t["ask"])*0.5 for ex,t in entries]
        mid=statistics.median(marks)
        entries=[(n,t) for n,t in entries if abs((t["bid"]+t["ask"])*0.5/mid-1)<0.10]
        for buy,bq in entries:
            if buy not in FUNDED:continue
            for sell,sq in entries:
                if sell not in FUNDED or sell==buy:continue
                if abs(bq["received"]-sq["received"])>12:continue
                spread=sq["bid"]/bq["ask"]-1
                if spread>=MIN_ENTRY_GAP:
                    opportunities.append((spread,coin,buy,sell))
    return sorted(opportunities,reverse=True)

def save(root,wallets,positions,realized,trades,venues,failures,start,attempted,open_value=None):
    summary={
      "utc":utc(),"elapsed_minutes":round((time.monotonic()-start)/60,2),
      "starting_equity_usdt":5000.0,
      "funded_wallets":{v:round(wallets[v],4) for v in FUNDED},
      "supported_exchanges":list(venues),
      "exchanges_attempted":attempted,
      "instrument_universe":len(COINS),
      "completed_pairs":trades,
      "open_pairs":len(positions),"open_position_details":[{"coin":p["coin"],"long":p["long_venue"],"short":p["short_venue"],"notional_usdt":round(p["notional"],2)} for p in positions],
      "realized_net_pnl_usdt":round(realized,4),
      "unrealized_net_pnl_usdt":round(open_value,4) if open_value is not None else None,
      "wallet_free_usdt":round(sum(wallets.values()),4),
      "reserved_margin_usdt":round(sum(p["long_margin"]+p["short_margin"] for p in positions),4),
      "exchange_errors":dict(failures),
      "warning":"Research-only simulation, no orders. REST ticker discovery is asynchronous, fills and close liquidity not guaranteed; venue contract specifics, funding, actual fee tiers, liquidation and market-impact risk not fully modeled. Open pairs are not realized profits."
    }
    if open_value is not None:
        summary["estimated_equity_usdt"]=round(
          summary["wallet_free_usdt"]+summary["reserved_margin_usdt"]
          +open_value+sum(p["open_fees"] for p in positions),4)
    (root/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    return summary

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--minutes",type=float,default=60)
    parser.add_argument("--poll",type=float,default=90)
    parser.add_argument("--output",default="/root/sol-arb-paper-20-aggressive/multicoin-v2")
    args=parser.parse_args()
    if args.minutes<=0 or args.poll<60:parser.error("minutes must be >0; --poll must be >=60 seconds")
    root=Path(args.output);root.mkdir(parents=True,exist_ok=True)
    logs=open(root/"events.jsonl","a",buffering=1)
    positions=[]
    wallets={name:500.0 for name in FUNDED}
    failures=Counter()
    realized=0.0
    closed=0
    start=time.monotonic()
    attempted=[]
    venues={}
    print("MULTICOIN V2 PAPER ONLY | 20 exchange candidates, 50 coins, 10 x $500 USDT perpetual paper margins",flush=True)
    print("No exchange credentials, no real orders. Positions must close to realize PnL.",flush=True)
    try:
        # Sequential market loading prevents a burst of 20 full market caches.
        for venue_id in VENUE_IDS:
            if time.monotonic()-start >= args.minutes*60:break
            rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if rss>MAX_MEMORY_KIB:
                print("Memory guard: stopping venue loading at",len(venues),"venues",flush=True)
                break
            if venue_id not in ccxt.exchanges:
                failures[venue_id+":unavailable"]+=1
                continue
            attempted.append(venue_id)
            try:
                info,n,error=setup_venue(venue_id)
                if info:
                    venues[venue_id]=info
                    print("exchange OK",venue_id,"compatible coins",n,flush=True)
                else:
                    failures[venue_id+":"+(error or "unsupported")]+=1
            except Exception as e:
                failures[venue_id+":"+type(e).__name__]+=1
                print("exchange skipped",venue_id,type(e).__name__,flush=True)
        print("ACTIVE VENUES",len(venues),"/20; funded capable",sum(v in venues for v in FUNDED),"/10",flush=True)
        if sum(v in venues for v in FUNDED)<2:
            print("Insufficient funded venues, no simulated trading.",flush=True)
            return
        with futures.ThreadPoolExecutor(max_workers=5) as pool:
            while time.monotonic()-start<args.minutes*60:
                tick=time.monotonic()
                # Tickers are for discovery only; books rechecked before any action.
                result=list(pool.map(fetch_tickers,venues.items()))
                quotes={}
                for name,q,error in result:
                    if error:
                        failures[name+":"+error.split(":")[0]]+=1
                    else:
                        quotes[name]=q
                open_coins={p["coin"] for p in positions}
                unrealized=0.0
                priceable=0
                # Try exiting every open pair against fresh books.
                for p in list(positions):
                    books=books_pair(p["long_venue"],p["short_venue"],p["coin"],venues,pool)
                    if not books:continue
                    est=hypothetical_close(p,*books)
                    if not est:continue
                    net,long_pnl,short_pnl,exit_fee,long_exit,short_exit=est
                    age=time.monotonic()-p["opened_at"]
                    should_close=(age>=45 and net>=max(0.10,p["notional"]*EXIT_PROFIT_FRACTION)) or (
                        net<=p["notional"]*STOP_LOSS_FRACTION or age>=MAX_HOLD_SECONDS)
                    if not should_close:
                        unrealized+=net
                        priceable+=1
                        continue
                    wallets[p["long_venue"]]+=p["long_margin"]+long_pnl-long_exit*p["qty"]*TAKER_FEE
                    wallets[p["short_venue"]]+=p["short_margin"]+short_pnl-short_exit*p["qty"]*TAKER_FEE
                    realized+=net
                    closed+=1
                    positions.remove(p)
                    record(logs,{"event":"CLOSE","utc":utc(),"coin":p["coin"],
                      "long":p["long_venue"],"short":p["short_venue"],
                      "qty":p["qty"],"net_realized_pnl_usdt":round(net,4),"held_seconds":round(age)})
                    print("CLOSE",p["coin"],"net",round(net,4),flush=True)
                open_coins={p["coin"] for p in positions}
                routes=rank_routes(quotes,open_coins,venues)
                for gap,coin,buy,sell in routes[:12]:
                    if len(positions)>=MAX_OPEN_PAIRS:break
                    if coin in open_coins:continue
                    books=books_pair(buy,sell,coin,venues,pool)
                    if not books:continue
                    long_book,short_book=books
                    # Size increases with verified top-of-book gap. Never exceed
                    # available unlevered simulated margin or visible order-book depth.
                    live_gap=short_book["bids"][0][0]/long_book["asks"][0][0]-1
                    if live_gap<MIN_ENTRY_GAP:continue
                    fraction=min(MAX_SHARE,0.30+max(0.0,live_gap-MIN_ENTRY_GAP)*23)
                    max_buy=wallets[buy]*fraction/(1+TAKER_FEE)
                    max_sell=wallets[sell]*fraction/(1+TAKER_FEE)
                    max_book=min(
                        available_amount(long_book["asks"]),
                        available_amount(short_book["bids"])
                    )*0.8
                    qty=min(max_buy/long_book["asks"][0][0],
                            max_sell/short_book["bids"][0][0],max_book)
                    if qty<=0:continue
                    ask=vwap(long_book["asks"],qty)
                    bid=vwap(short_book["bids"],qty)
                    if not ask or not bid:continue
                    # Pessimistic two-sided slippage and open+close fee hurdle.
                    long_entry=ask*(1+SLIPPAGE)
                    short_entry=bid*(1-SLIPPAGE)
                    effective_gap=short_entry/long_entry-1
                    min_roundtrip=4*TAKER_FEE+2*SLIPPAGE+EXIT_PROFIT_FRACTION
                    if effective_gap<min_roundtrip:continue
                    notional=qty*long_entry
                    if notional<MIN_NOTIONAL:continue
                    long_margin=notional
                    short_margin=qty*short_entry
                    fees=TAKER_FEE*(long_margin+short_margin)
                    long_open_fee=TAKER_FEE*long_margin
                    short_open_fee=TAKER_FEE*short_margin
                    if wallets[buy]<long_margin+long_open_fee or wallets[sell]<short_margin+short_open_fee:continue
                    wallets[buy]-=long_margin+long_open_fee
                    wallets[sell]-=short_margin+short_open_fee
                    p={"coin":coin,"long_venue":buy,"short_venue":sell,"qty":qty,
                       "long_entry":long_entry,"short_entry":short_entry,
                       "long_margin":long_margin,"short_margin":short_margin,
                       "open_fees":fees,"notional":notional,"opened_at":time.monotonic()}
                    positions.append(p)
                    open_coins.add(coin)
                    record(logs,{"event":"OPEN","utc":utc(),"coin":coin,"long":buy,
                        "short":sell,"qty":qty,"notional_usdt":round(notional,3),
                        "verified_gap_pct":round(live_gap*100,4),"sizing_fraction":round(fraction,3)})
                    print("OPEN",coin,buy,sell,"notional",round(notional,2),
                          "gap%",round(live_gap*100,3),flush=True)
                # Do not include open position profits in realized PnL.
                # Open-value computation is only complete if ALL open legs were priced.
                open_value=unrealized if priceable==len(positions) and not any(
                    p["opened_at"]>=tick for p in positions) else None
                summary=save(root,wallets,positions,realized,closed,venues,failures,start,attempted,open_value)
                print("STATUS",summary["elapsed_minutes"],"min",len(quotes),"quote venues",
                      "open",len(positions),"closed",closed,"realized",round(realized,3),flush=True)
                time.sleep(max(0,args.poll-(time.monotonic()-tick)))
    except KeyboardInterrupt:
        print("Stopped by operator; saving paper state.",flush=True)
    finally:
        summary=save(root,wallets,positions,realized,closed,venues,failures,start,attempted,None)
        record(logs,{"event":"FINAL","summary":summary})
        print("SUMMARY",json.dumps(summary,indent=2),flush=True)
        logs.close()

if __name__=="__main__":
    main()
