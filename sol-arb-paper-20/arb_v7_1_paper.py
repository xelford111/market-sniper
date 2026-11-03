#!/usr/bin/env python3
"""
V7: 5 wallet x 1000 USDT forward-only, paper-only cross-venue USDT perpetual
spread-convergence observer. Requires CURRENT order books. No API keys.
No exchange write/order capability anywhere in the program.
CCXT book quantity interpretation and funding assumptions still require
venue-specific certification before considering real execution.
"""
import argparse
import concurrent.futures as futures
import datetime as dt
import fcntl
import json
import math
import os
import signal
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

VERSION="V7.1-PAPER-RESEARCH"
VENUES=("okx","bitget","gate","mexc","bingx")
INITIAL_USDT=1000.0
LEVERAGE=5.0
COLLATERAL_CAP=0.50
MAX_PAIR_LOSS_USDT=25.0
MAX_TOTAL_REALIZED_LOSS_USDT=150.0
MAX_CONSECUTIVE_LOSSES=3
MAX_ACTIVE_PAIRS=2
FEE=0.0006           # estimated taker fee PER FILL
EXTRA_SLIP=0.0005    # estimated adverse slippage PER FILL
FUNDING_RESERVE=0.0004 # scenario buffer on long+short notional combined
MIN_GROSS_TICKER_GAP=0.004
RESEARCH_GROSS_GAP=0.0015 # 0.15% *monitoring*, NOT trade entry
ILLUSTRATIVE_MAKER_FEE=0.0002 # not actual connected account fee tier
MIN_GROSS_BOOK_GAP=0.006
MIN_NET_CONVERGENCE_SCENARIO=2.0
MIN_MARGIN_PER_LEG=15.0
ORDERBOOK_LIMIT=20
MAX_BOOK_RECEIVE_SKEW=2.5
MAX_BOOK_SOURCE_AGE_MS=5000
CONFIRM_INTERVAL_S=1.0
CANDIDATE_COOLDOWN_S=30
MAX_HOLD_SECONDS=900
UNPRICED_EXIT_FREEZE_SECONDS=50
STATE_VERSION=7
COINS_PRIORITY=(
    "BTC ETH SOL XRP DOGE BNB ADA LINK AVAX LTC TRX DOT BCH UNI XLM ETC "
    "APT ARB OP SUI NEAR FIL ATOM ICP AAVE PEPE SHIB INJ POL TON "
    "WIF BONK FET RUNE GRT SEI TIA STX JUP ENA MKR ALGO HBAR "
    "SAND MANA CRV LDO IMX FLOKI ONDO NEO EOS DYDX GMX ZEC "
    "DASH COMP SNX KAVA LRC GALA AXS CHZ XTZ EGLD ZIL 1INCH "
    "ZRX MASK ROSE CELO MINA IOTA ENS SUSHI YFI QTUM KSM CFX "
    "WLD BLUR PYTH WOO MEME TURBO ORDI BOME NOT BRETT POPCAT "
    "PNUT PENGU VIRTUAL JASMY ZRO STRK ZK KAIA RAY FARTCOIN "
    "ETHFI SSV SUPER PENDLE OM"
).split()

def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def positive(x):
    try:
        v=float(x)
        return v if math.isfinite(v) and v>0 else None
    except (TypeError,ValueError):
        return None

def save_json(path,data):
    temp=path.with_suffix(path.suffix+".tmp")
    with temp.open("w",encoding="utf-8") as f:
        json.dump(data,f,indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp,path)

def event(path,kind,**fields):
    record={"utc":utc(),"kind":kind,**fields}
    with path.open("a",encoding="utf-8") as f:
        f.write(json.dumps(record,separators=(",",":"))+"\n")
        f.flush()

def wallet_seed():
    return {venue:INITIAL_USDT for venue in VENUES}

def fresh_state():
    return {
        "version":STATE_VERSION,"created_utc":utc(),"wallets":wallet_seed(),
        "positions":[],"closed":0,"wins":0,"losses":0,"consecutive_losses":0,
        "realized_net_usdt":0.0,"paused_reason":None,"cycles":0,
        "diagnostics":{},"venue_status":{},"top_discovery":[],
        "book_validations":[],"research_history":[],"total_candidates":0
    }

def load_state(path):
    if not path.exists():
        return fresh_state()
    x=json.loads(path.read_text())
    if x.get("version")!=STATE_VERSION or set(x.get("wallets",{}))!=set(VENUES):
        raise RuntimeError("Existing state/config incompatible. Refusing to overwrite.")
    return x

def cash_and_margin(state):
    cash=sum(state["wallets"].values())
    reserved=sum(p["margin_long"]+p["margin_short"] for p in state["positions"])
    return cash,reserved

def vwap(book_side,base_qty):
    remain=base_qty
    value=0.0
    for price,qty in book_side:
        q=min(remain,qty)
        value+=q*price
        remain-=q
        if remain<=max(base_qty*1e-10,1e-12):
            return value/base_qty
    return None

def depth_base(book_raw,market):
    # Conservative order book quantity heuristic:
    # if futures book volume is in contracts, contractSize converts to base.
    # if already base, scaling down by CS<1 understates accessible liquidity.
    # Not yet a certified adapter for live execution on ANY venue.
    size=positive(market.get("contractSize")) or 1.0
    factor=min(1.0,size)
    sides={}
    for side,reverse in (("bids",True),("asks",False)):
        values=[]
        for level in book_raw.get(side,[])[:ORDERBOOK_LIMIT]:
            if len(level)<2:continue
            price,qty=positive(level[0]),positive(level[1])
            if price and qty:
                values.append((price,qty*factor))
        values.sort(key=lambda p:p[0],reverse=reverse)
        sides[side]=values
    if not sides["asks"] or not sides["bids"]:
        return None
    if sides["bids"][0][0]>=sides["asks"][0][0]:
        return None
    return sides

def quote_safe(book,now_ms,received):
    if book.get("timestamp") is None:
        return True,False
    try:
        age=now_ms-float(book["timestamp"])
        return (-3000<=age<=MAX_BOOK_SOURCE_AGE_MS),True
    except (ValueError,TypeError):
        return False,True

def good_market(m):
    return (m.get("swap") is True and m.get("linear") is True and
            m.get("quote")=="USDT" and m.get("settle")=="USDT" and
            m.get("active") is not False and bool(m.get("base")))

class Venue:
    def __init__(self,name):
        self.name=name
        self.ex=None
        self.markets={}
        self.errors=[]
        self.health="INIT"
        self.last_scan=0.0
        self.last_quotes={}
    def connect(self):
        import ccxt
        if self.name not in ccxt.exchanges:
            raise RuntimeError("CCXT venue ID unavailable")
        self.ex=getattr(ccxt,self.name)({
            "enableRateLimit":True,"timeout":12000,
            "options":{"defaultType":"swap"},
        })
        self.ex.load_markets()
        for symbol,m in self.ex.markets.items():
            if good_market(m) and m["base"] not in self.markets:
                self.markets[m["base"]]=(symbol,m)
        if not self.markets:
            raise RuntimeError("No usable USDT-settled linear swap markets")
        if not self.ex.has.get("fetchOrderBook"):
            raise RuntimeError("No public order book support")
        self.health="READY"
    def ticker_scan(self,coins):
        if self.ex is None:
            return None
        # Unified tickers are DISCOVERY ONLY, never treated as executable bids.
        choices=[self.markets[c][0] for c in coins if c in self.markets]
        if not choices:
            return {"received":time.monotonic(),"quotes":{}}
        if not self.ex.has.get("fetchTickers"):
            return {"received":time.monotonic(),"quotes":{}}
        try:
            data=self.ex.fetch_tickers(choices)
        except Exception:
            # Retry generic bulk query if venue does not support symbol filters.
            data=self.ex.fetch_tickers()
        receive=time.monotonic()
        quotes={}
        for coin in coins:
            if coin not in self.markets:continue
            symbol=self.markets[coin][0]
            x=data.get(symbol)
            if not isinstance(x,dict):continue
            bid,ask=positive(x.get("bid")),positive(x.get("ask"))
            if not bid or not ask or bid>=ask:continue
            ts=x.get("timestamp")
            if ts is not None:
                try:
                    lag=time.time()*1000-float(ts)
                    if lag>20000 or lag< -5000:continue
                except (TypeError,ValueError):continue
            quotes[coin]=(bid,ask)
        self.last_quotes=quotes
        self.last_scan=receive
        return {"received":receive,"quotes":quotes}
    def book(self,coin):
        if self.ex is None or coin not in self.markets:
            return None
        symbol,market=self.markets[coin]
        raw=self.ex.fetch_order_book(symbol,limit=ORDERBOOK_LIMIT)
        recv=time.monotonic()
        wall_ms=time.time()*1000
        safe,has_source_time=quote_safe(raw,wall_ms,recv)
        sides=depth_base(raw,market)
        if not safe or sides is None:
            return None
        return {"venue":self.name,"coin":coin,"market":market,"symbol":symbol,
                "received":recv,"timestamp_present":has_source_time,
                **sides}
    def quantize(self,coin,quantity_base):
        symbol,market=self.markets[coin]
        cs=positive(market.get("contractSize")) or 1.0
        # CCXT derivative amount_to_precision takes contract quantities.
        try:
            contracts=float(self.ex.amount_to_precision(symbol,quantity_base/cs))
        except Exception:
            return None
        if contracts<=0:return None
        min_amount=(market.get("limits") or {}).get("amount") or {}
        if positive(min_amount.get("min")) and contracts<float(min_amount["min"]):
            return None
        base=contracts*cs
        return base if base>0 else None

def two_books(pool,venues,a,b,coin):
    job_l=pool.submit(venues[a].book,coin)
    job_s=pool.submit(venues[b].book,coin)
    try:
        book_l=job_l.result(timeout=24)
        book_s=job_s.result(timeout=24)
    except Exception:
        return None
    if not book_l or not book_s:return None
    if abs(book_l["received"]-book_s["received"])>MAX_BOOK_RECEIVE_SKEW:
        return None
    return book_l,book_s

def discovery(quotes):
    # Note that cross-venue ticker snapshots have different times.
    # This is only a research ranking, not an entry trigger.
    bycoin={}
    for venue,item in quotes.items():
        if not item:continue
        for coin,bidask in item["quotes"].items():
            bycoin.setdefault(coin,[]).append((venue,bidask))
    observed=[]
    for coin,values in bycoin.items():
        if len(values)<2:continue
        midpoint=statistics.median((x[1][0]+x[1][1])/2 for x in values)
        values=[x for x in values if abs((x[1][0]+x[1][1])/(2*midpoint)-1)<0.04]
        for v1,(bid1,ask1) in values:
            for v2,(bid2,ask2) in values:
                if v1!=v2:
                    gap=bid2/ask1-1
                    if 0<gap<0.05:
                        observed.append((gap,coin,v1,v2))
    observed.sort(reverse=True)
    return observed


def research_scenario(state,venues,buy,sell,coin,books):
    """Read-only, size-limited illustrative *full convergence* arithmetic.

    Two models are compared on observed orderbook depth:
    1) taker: four taker fees, four adverse slippage adjustments, funding buffer.
    2) maker: fee-only optimistic upper bound, assuming all four orders fill
       at the *same* depth-based prices, with no extra slippage.
       This is NOT an executable maker strategy or expected profit.
    """
    l,r=books
    gross_gap=r["bids"][0][0]/l["asks"][0][0]-1
    if buy not in state["wallets"] or sell not in state["wallets"]:
        return {"reason":"unfunded_route"}
    cap_l=max(0.0,state["wallets"][buy])*COLLATERAL_CAP
    cap_s=max(0.0,state["wallets"][sell])*COLLATERAL_CAP
    if cap_l<MIN_MARGIN_PER_LEG or cap_s<MIN_MARGIN_PER_LEG:
        return {"reason":"insufficient_available_collateral"}
    qty=min(
        cap_l*LEVERAGE/(l["asks"][0][0]*(1+FEE*LEVERAGE+EXTRA_SLIP)),
        cap_s*LEVERAGE/(r["bids"][0][0]*(1+FEE*LEVERAGE+EXTRA_SLIP)),
        sum(q for _,q in l["asks"])*0.30,
        sum(q for _,q in r["bids"])*0.30
    )
    if qty<=0:
        return {"reason":"no_depth"}
    qa=venues[buy].quantize(coin,qty)
    qb=venues[sell].quantize(coin,qty)
    if not qa or not qb:
        return {"reason":"lot_precision"}
    qty=min(qa,qb)
    qa2=venues[buy].quantize(coin,qty)
    qb2=venues[sell].quantize(coin,qty)
    if not qa2 or not qb2 or abs(qa2-qb2)>max(1e-10,qty*1e-5):
        return {"reason":"mismatched_contract_lots"}
    qty=min(qa2,qb2)
    p_buy=vwap(l["asks"],qty)
    p_sell=vwap(r["bids"],qty)
    if not p_buy or not p_sell:
        return {"reason":"not_enough_depth"}
    notional_l=qty*p_buy
    notional_s=qty*p_sell
    gross=qty*(p_sell-p_buy)
    two_sided=notional_l+notional_s
    fees_4_taker=2*FEE*two_sided
    slippage_4=2*EXTRA_SLIP*two_sided
    funding_buffer=FUNDING_RESERVE*two_sided
    taker_full=gross-fees_4_taker-slippage_4-funding_buffer
    maker_fee_only=gross-2*ILLUSTRATIVE_MAKER_FEE*two_sided-funding_buffer
    return {
      "fresh_book_gap_pct":round(gross_gap*100,4),
      "notional_per_leg_usdt":round(two_sided/2,2),
      "margin_per_leg_usdt":round(two_sided/(2*LEVERAGE),2),
      "gross_full_convergence_usdt":round(gross,4),
      "estimated_taker_costs_and_buffer_usdt":round(
          fees_4_taker+slippage_4+funding_buffer,4),
      "taker_full_convergence_usdt":round(taker_full,4),
      "maker_fee_only_upper_bound_usdt":round(maker_fee_only,4),
      "both_book_timestamps":bool(l["timestamp_present"] and r["timestamp_present"]),
      "note":"Theoretical full spread convergence only. Not expected P&L or executable maker fill."
    }

def append_research_sample(state,entry):
    history=state.setdefault("research_history",[])
    # A bounded rolling history can survive process restart. If more than one
    # snapshot confirms the same route within 15 minutes, say so explicitly.
    key=(entry["coin"],entry["buy"],entry["sell"])
    now=time.time()
    history[:]=[x for x in history if now-x.get("sampled_epoch",0)<3600][-240:]
    matching=[x for x in history if
              (x.get("coin"),x.get("buy"),x.get("sell"))==key and
              now-x.get("sampled_epoch",0)<900 and
              x.get("fresh_book_gap_pct",0)>0]
    entry["positive_samples_15m_including_current"]=(len(matching)+1) if entry.get("fresh_book_gap_pct",0)>0 else 0
    entry["sampled_epoch"]=now
    history.append(entry)
    state["research_history"]=history[-240:]

def entry_estimate(state,venues,long_v,short_v,coin,books):
    left,right=books
    if long_v not in state["wallets"] or short_v not in state["wallets"]:
        return None,"unfunded_route"
    if long_v==short_v:return None,"same_venue"
    if long_v not in venues or short_v not in venues:return None,"missing_venue"
    if coin not in venues[long_v].markets or coin not in venues[short_v].markets:
        return None,"different_contracts"
    gross_gap=right["bids"][0][0]/left["asks"][0][0]-1
    if gross_gap<MIN_GROSS_BOOK_GAP:
        return None,"gross_gap_too_small"
    cash_a=state["wallets"][long_v]
    cash_b=state["wallets"][short_v]
    # One position per venue with <=20% of its free paper balance.
    # Always 20% of the CURRENT free wallet balance: losses shrink sizing;
    # realized gains gradually increase sizing. No fixed $200 ceiling.
    cap_a=max(0.0,cash_a)*COLLATERAL_CAP
    cap_b=max(0.0,cash_b)*COLLATERAL_CAP
    size_a=cap_a*LEVERAGE/(left["asks"][0][0]*(1+FEE*LEVERAGE+EXTRA_SLIP))
    size_b=cap_b*LEVERAGE/(right["bids"][0][0]*(1+FEE*LEVERAGE+EXTRA_SLIP))
    depth_a=sum(q for _,q in left["asks"])*0.30
    depth_b=sum(q for _,q in right["bids"])*0.30
    qty=min(size_a,size_b,depth_a,depth_b)
    if qty<=0:return None,"no_liquidity_or_cash"
    qa=venues[long_v].quantize(coin,qty)
    qb=venues[short_v].quantize(coin,qty)
    if qa is None or qb is None:return None,"contract_lot_precision"
    qty=min(qa,qb)
    # Strict base-unit matching for both legs. If lot steps disagree,
    # skip rather than claiming a perfectly hedged fill.
    qa2=venues[long_v].quantize(coin,qty)
    qb2=venues[short_v].quantize(coin,qty)
    if not qa2 or not qb2 or abs(qa2-qb2)>max(1e-10,qty*1e-5):
        return None,"contract_lot_mismatch"
    qty=min(qa2,qb2)
    buy_vwap=vwap(left["asks"],qty)
    sell_vwap=vwap(right["bids"],qty)
    if not buy_vwap or not sell_vwap:
        return None,"not_enough_order_book_depth"
    # Worst-case adverse slip applied to all four market fills.
    buy_exec=buy_vwap*(1+EXTRA_SLIP)
    sell_exec=sell_vwap*(1-EXTRA_SLIP)
    margin_l=qty*buy_exec/LEVERAGE
    margin_s=qty*sell_exec/LEVERAGE
    entry_fee_l=qty*buy_exec*FEE
    entry_fee_s=qty*sell_exec*FEE
    if min(margin_l,margin_s)<MIN_MARGIN_PER_LEG:
        return None,"below_minimum_margin"
    if margin_l+entry_fee_l>cap_a or margin_s+entry_fee_s>cap_b:
        return None,"exceeds_collateral_cap"
    # Hypothetical FULL convergence scenario, NOT a probability forecast.
    gross_usdt=qty*(sell_vwap-buy_vwap)
    estimated_roundtrip_fees=qty*(buy_vwap+sell_vwap)*2*FEE
    estimated_four_fills_slippage=qty*(buy_vwap+sell_vwap)*2*EXTRA_SLIP
    reserve=qty*(buy_vwap+sell_vwap)*FUNDING_RESERVE
    scenario=gross_usdt-estimated_roundtrip_fees-estimated_four_fills_slippage-reserve
    if scenario<MIN_NET_CONVERGENCE_SCENARIO:
        return None,"not_enough_scenario_after_costs"
    return {
      "coin":coin,"long":long_v,"short":short_v,"qty":qty,
      "long_entry":buy_exec,"short_entry":sell_exec,
      "margin_long":margin_l,"margin_short":margin_s,
      "entry_fee_long":entry_fee_l,"entry_fee_short":entry_fee_s,
      "entry_fees":entry_fee_l+entry_fee_s,
      "entry_gross_gap_pct":round(gross_gap*100,4),
      "estimated_full_convergence_usdt":round(scenario,4),
      "funding_scenario_reserve_usdt":round(reserve,4),
      "notional_per_leg_usdt":round(qty*(buy_exec+sell_exec)/2,2),
      "books_timestamp_present":bool(left["timestamp_present"] and right["timestamp_present"])
    },None

def mark_exit(pos,books):
    l,s=books
    qty=pos["qty"]
    exit_l=vwap(l["bids"],qty)
    exit_s=vwap(s["asks"],qty)
    if not exit_l or not exit_s:return None
    exit_l*=1-EXTRA_SLIP
    exit_s*=1+EXTRA_SLIP
    gross_l=qty*(exit_l-pos["long_entry"])
    gross_s=qty*(pos["short_entry"]-exit_s)
    fee_l=qty*exit_l*FEE
    fee_s=qty*exit_s*FEE
    net=gross_l+gross_s-pos["entry_fees"]-fee_l-fee_s
    return {"net":net,"gross_l":gross_l,"gross_s":gross_s,
            "close_fee_l":fee_l,"close_fee_s":fee_s,
            "exit_long":exit_l,"exit_short":exit_s}

def open_paper(state,order,events_path):
    a,b=order["long"],order["short"]
    state["wallets"][a]-=order["margin_long"]+order["entry_fee_long"]
    state["wallets"][b]-=order["margin_short"]+order["entry_fee_short"]
    pos={**order,"opened_at":utc(),"opened_epoch":time.time(),
         "last_valid_mark_at":time.time(),"latest_mark":None}
    state["positions"].append(pos)
    event(events_path,"OPEN",coin=order["coin"],long=a,short=b,
          gross_gap_pct=order["entry_gross_gap_pct"],
          margin_per_leg=[round(order["margin_long"],2),round(order["margin_short"],2)],
          notional_per_leg=order["notional_per_leg_usdt"],
          scenario_usdt=order["estimated_full_convergence_usdt"])
    return pos

def close_paper(state,pos,mark,reason,events_path):
    state["wallets"][pos["long"]]+=pos["margin_long"]+mark["gross_l"]-mark["close_fee_l"]
    state["wallets"][pos["short"]]+=pos["margin_short"]+mark["gross_s"]-mark["close_fee_s"]
    net=mark["net"]
    state["realized_net_usdt"]+=net
    state["closed"]+=1
    if net>0:
        state["wins"]+=1
        state["consecutive_losses"]=0
    else:
        state["losses"]+=1
        state["consecutive_losses"]+=1
    if (state["realized_net_usdt"]<=-MAX_TOTAL_REALIZED_LOSS_USDT or
        state["consecutive_losses"]>=MAX_CONSECUTIVE_LOSSES):
        state["paused_reason"]="realized_drawdown_or_loss_streak"
    state["positions"].remove(pos)
    event(events_path,"CLOSE",coin=pos["coin"],long=pos["long"],short=pos["short"],
          net_usdt=round(net,4),reason=reason,
          seconds_open=round(time.time()-pos["opened_epoch"]))
    return net

def evaluate_open_marks(state,venues,pool,events_path):
    unmarked=0
    marks={}
    for pos in list(state["positions"]):
        books=two_books(pool,venues,pos["long"],pos["short"],pos["coin"])
        if books is None:
            unmarked+=1
            if time.time()-pos["last_valid_mark_at"]>=UNPRICED_EXIT_FREEZE_SECONDS:
                state["paused_reason"]="open_position_unpriced"
            continue
        mark=mark_exit(pos,books)
        if mark is None:
            unmarked+=1
            continue
        pos["last_valid_mark_at"]=time.time()
        pos["latest_mark"]={"net_usdt":round(mark["net"],4),"utc":utc()}
        marks[(pos["long"],pos["short"],pos["coin"])]=mark
        age=time.time()-pos["opened_epoch"]
        # stop is based on an OBSERVED quote, not a guaranteed loss boundary.
        # Liquidation may occur sooner between polling intervals.
        exposure=pos["notional_per_leg_usdt"]
        if mark["net"]<=-MAX_PAIR_LOSS_USDT:
            reason="INTENDED_LOSS_LIMIT"
        elif age>=MAX_HOLD_SECONDS:
            reason="TIME_LIMIT"
        elif mark["net"]>=max(2.0,0.002*exposure):
            reason="POSITIVE_NET_AFTER_COSTS"
        else:
            reason=None
        if reason:
            value=close_paper(state,pos,mark,reason,events_path)
            print("✅ CLOSE",pos["coin"],pos["long"],pos["short"],
                  f"{value:+.3f} USDT",reason,flush=True)
    return unmarked,marks

def snapshot(state,unmarked,marks,coins_count):
    free,reserved=cash_and_margin(state)
    # Position entry fees were already subtracted from free; net marked
    # exit includes them, hence add entry fees back exactly once.
    if unmarked==0 and len(marks)==len(state["positions"]):
        net=sum(m["net"] for m in marks.values())
        entryfees=sum(p["entry_fees"] for p in state["positions"])
        equity=free+reserved+net+entryfees
    elif not state["positions"]:
        net=0.0
        equity=free
    else:
        net=None
        equity=None
    return {
      "utc":utc(),"version":VERSION,"mode":"PAPER ONLY / forward public-order-book samples",
      "wallets_seed_usdt":{v:INITIAL_USDT for v in VENUES},
      "starting_equity_usdt":INITIAL_USDT*len(VENUES),
      "funded_wallets":{v:round(x,3) for v,x in state["wallets"].items()},
      "venues":list(VENUES),"venue_status":state["venue_status"],
      "coin_universe":coins_count,"leverage_x":LEVERAGE,
      "collateral_cap_per_wallet":COLLATERAL_CAP,
      "intended_pair_loss_cap_usdt":MAX_PAIR_LOSS_USDT,
      "free_equity_usdt":round(free,3),"reserved_margin_usdt":round(reserved,3),
      "realized_net_pnl_usdt":round(state["realized_net_usdt"],4),
      "unrealized_exit_net_pnl_usdt":round(net,4) if net is not None else None,
      "estimated_marked_equity_usdt":round(equity,3) if equity is not None else None,
      "unpriced_open_positions":unmarked,
      "open_pairs":len(state["positions"]),"closed_pairs":state["closed"],
      "wins":state["wins"],"losses":state["losses"],
      "positions":[{"coin":p["coin"],"long":p["long"],"short":p["short"],
          "open_epoch":p["opened_epoch"],"notional_per_leg_usdt":p["notional_per_leg_usdt"],
          "margin_long":round(p["margin_long"],3),"margin_short":round(p["margin_short"],3),
          "mark":p.get("latest_mark")} for p in state["positions"]],
      "paused_reason":state["paused_reason"],"cycles":state["cycles"],
      "candidate_count_total":state["total_candidates"],
      "top_discovery":state["top_discovery"],
      "book_validations":state["book_validations"][-15:],
      "research_samples":state.get("research_history",[])[-24:],
      "research_gap_threshold_pct":RESEARCH_GROSS_GAP*100,
      "maker_scenario_fee_per_fill":ILLUSTRATIVE_MAKER_FEE,
      "diagnostics":state["diagnostics"],
      "limitations":[
         "Quote snapshots are sampled asynchronously; even a second fresh book cannot guarantee simultaneous real fills.",
         "Conservative book-quantity contractSize heuristic NOT venue certified.",
         "Fees and slippage are assumptions; actual exchange fee tiers, funding cash flows, liquidation rules, partial fills and outages are not modeled.",
         "$25 is an intended paper exit threshold, NOT a guaranteed maximum loss.",
         "There is no automatic promotion to live orders. No exchange credentials are used."
      ]
    }

def choose_coins(venues,limit):
    # Only currencies supported by two or more of the funded five venues.
    counts=Counter()
    for v in venues.values():
        counts.update(v.markets.keys())
    coins=[c for c,n in counts.items() if n>=2]
    priority={c:i for i,c in enumerate(COINS_PRIORITY)}
    coins.sort(key=lambda c:(0,priority[c]) if c in priority else (1,c))
    return coins[:limit]

def self_test():
    state=fresh_state()
    assert len(state["wallets"])==5 and "bingx" in VENUES
    assert sum(state["wallets"].values())==5000.0
    assert LEVERAGE==5 and COLLATERAL_CAP==0.50
    assert RESEARCH_GROSS_GAP==0.0015 and MIN_GROSS_BOOK_GAP==0.006
    book={"bids":[[100.0,20.0]],"asks":[[100.2,20.0]]}
    meta={"contractSize":0.1}
    norm=depth_base(book,meta)
    assert norm and norm["bids"][0][1]==2.0
    assert abs(vwap([(100.0,1.0),(101.0,2.0)],2.0)-100.5)<1e-9
    assert vwap([(100,0.01)],1.0) is None
    class StubVenue:
        def __init__(self,cs=0.001):
            self.markets={"SOL":("SOL/USDT:USDT",{"contractSize":cs})}
            self.cs=cs
        def quantize(self,coin,qty):
            return math.floor(qty/self.cs)*self.cs
    venues={"okx":StubVenue(),"bitget":StubVenue()}
    # Market mapping is a dict[str,(symbol,market)]. Counting the mapping
    # itself would incorrectly add tuple values as Counter increments.
    assert choose_coins(venues,5)==["SOL"]
    b1={"bids":[(100.0,100)],"asks":[(100.1,100)],
        "timestamp_present":True}
    b2={"bids":[(101.0,100)],"asks":[(101.1,100)],
        "timestamp_present":True}
    research=research_scenario(state,venues,"okx","bitget","SOL",(b1,b2))
    assert "reason" not in research,research
    assert research["maker_fee_only_upper_bound_usdt"]>research["taker_full_convergence_usdt"]
    sample={"coin":"SOL","buy":"okx","sell":"bitget",**research}
    append_research_sample(state,sample)
    assert sample["positive_samples_15m_including_current"]==1
    append_research_sample(state,{"coin":"SOL","buy":"okx","sell":"bitget",**research})
    assert state["research_history"][-1]["positive_samples_15m_including_current"]==2
    x,err=entry_estimate(state,venues,"okx","bitget","SOL",(b1,b2))
    assert err is None,err
    assert x["margin_long"]+x["entry_fee_long"]<=500
    assert x["margin_short"]+x["entry_fee_short"]<=500
    out=Path("/tmp/v7-selftest-events-"+str(os.getpid())+".jsonl")
    open_paper(state,x,out)
    # mark at favorable closing prices, then check wallet P&L conservation
    close_books=({"bids":[(100.7,100)],"asks":[(100.8,100)]},
                 {"bids":[(100.5,100)],"asks":[(100.6,100)]})
    m=mark_exit(x,close_books)
    assert m is not None
    equity=snapshot(state,0,{("okx","bitget","SOL"):m},2)["estimated_marked_equity_usdt"]
    assert equity is not None and math.isfinite(equity)
    net=close_paper(state,state["positions"][0],m,"TEST",out)
    assert abs(sum(state["wallets"].values())-(5000+net))<1e-8
    assert abs(snapshot(state,0,{},2)["estimated_marked_equity_usdt"]-(5000+net))<0.002
    out.unlink(missing_ok=True)
    print("✅ V7 paper wallet, costs, margin, book and P&L arithmetic tests PASS")
    print("🔒 No external exchange calls or real orders")

def run(a):
    root=Path(a.out)
    root.mkdir(parents=True,exist_ok=True)
    lock_fd=(root/"engine.lock").open("a")
    try:
        fcntl.flock(lock_fd.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError("Another V7 process is already running for this output.")
    state_path=root/"state.json"
    events_path=root/"events.jsonl"
    state=load_state(state_path)
    print("🚀 V7 FORWARD PAPER ONLY | 5×1,000 USDT | 5x | 20% per-wallet cap",flush=True)
    print("🛑 No credentials, no real orders, no SpotX/VENOM modifications",flush=True)
    print("📚 Loading markets for funded venues:",", ".join(VENUES),flush=True)
    venues={}
    for name in VENUES:
        v=Venue(name)
        try:
            v.connect()
            venues[name]=v
            state["venue_status"][name]={"status":"READY","markets":len(v.markets)}
            print("✅",name,len(v.markets),"USDT perps",flush=True)
        except Exception as ex:
            state["venue_status"][name]={"status":"UNAVAILABLE","error":str(ex)[:130]}
            print("❌",name,str(ex)[:130],flush=True)
    if len(venues)<2:
        save_json(state_path,state)
        save_json(root/"summary.json",snapshot(state,0,{},0))
        print("⚠️ Fewer than 2 venues accessible; no simulated trades.",flush=True)
        return
    coins=choose_coins(venues,a.coins)
    if len(coins)<5:
        print("⚠️ Fewer than 5 common markets. Monitoring without opening.",flush=True)
    else:
        print("🪙",len(coins),"common USDT perps; only first",a.coins,"considered",flush=True)
    for item in state["positions"]:
        if item["long"] not in venues or item["short"] not in venues:
            state["paused_reason"]="open_position_venue_unavailable"
    start=time.monotonic()
    next_end=start+a.minutes*60
    last_checked={}
    stop_requested=False
    def on_signal(sig,frame):
        nonlocal stop_requested
        stop_requested=True
    signal.signal(signal.SIGTERM,on_signal)
    signal.signal(signal.SIGINT,on_signal)
    try:
        with futures.ThreadPoolExecutor(max_workers=min(5,len(venues))) as pool:
            while not stop_requested and time.monotonic()<next_end:
                cycle_start=time.monotonic()
                d=state["diagnostics"]
                try:
                    unmarked,marks=evaluate_open_marks(state,venues,pool,events_path)
                    if unmarked:
                        d["unpriced_marks"]=d.get("unpriced_marks",0)+unmarked
                except Exception as e:
                    unmarked=len(state["positions"])
                    marks={}
                    state["paused_reason"]="position_monitor_exception"
                    print("⚠️ POSITION MARK ERROR",type(e).__name__,str(e)[:100],flush=True)
                # Only fresh books may cause entry; tickers rank candidates.
                quote_jobs={name:pool.submit(v.ticker_scan,coins)
                            for name,v in venues.items()}
                scans={}
                for name,job in quote_jobs.items():
                    try:
                        scans[name]=job.result(timeout=25)
                        state["venue_status"][name]={"status":"UP","markets":len(venues[name].markets),
                                  "ticker_coins":len(scans[name]["quotes"])}
                    except Exception as ex:
                        state["venue_status"][name]={"status":"ERROR","error":str(ex)[:140]}
                        d["ticker_errors"]=d.get("ticker_errors",0)+1
                all_observed=discovery(scans)
                seen=[x for x in all_observed if x[0]>=MIN_GROSS_TICKER_GAP]
                state["total_candidates"]+=len(seen)
                state["top_discovery"]=[{"coin":coin,"buy":buy,"sell":sell,
                     "discovery_gap_pct":round(gap*100,4),
                     "eligible_for_book_check":gap>=MIN_GROSS_TICKER_GAP,
                     "warning":"Observed ticker gap only — not executable"}
                     for gap,coin,buy,sell in all_observed[:12]]
                # Read-only research from 0.15%+ ticker gap. Rotate through
                # leading routes, confirm fresh books and store real size-cost
                # scenarios; do NOT loosen the 0.4% ticker/0.6% book trade gates.
                study=[x for x in all_observed if x[0]>=RESEARCH_GROSS_GAP]
                watch=study[state["cycles"]%min(4,len(study))] if study else None
                if watch is None and "SOL" in coins:
                    ready=[name for name,v in venues.items() if "SOL" in v.markets]
                    if len(ready)>=2:
                        watch=(0.0,"SOL",ready[0],ready[1])
                if watch is not None:
                    _,watchcoin,watchbuy,watchsell=watch
                    try:
                        sample=two_books(pool,venues,watchbuy,watchsell,watchcoin)
                        if sample:
                            analysis=research_scenario(
                                state,venues,watchbuy,watchsell,watchcoin,sample)
                            entry={"utc":utc(),"coin":watchcoin,
                                   "buy":watchbuy,"sell":watchsell,
                                   "ticker_gap_pct":round(watch[0]*100,4)}
                            if "reason" in analysis:
                                entry.update({"reason":analysis["reason"]})
                                d["research_"+analysis["reason"]]=d.get(
                                    "research_"+analysis["reason"],0)+1
                            else:
                                entry.update(analysis)
                                d["research_depth_cost_samples"]=d.get(
                                    "research_depth_cost_samples",0)+1
                                if analysis["taker_full_convergence_usdt"]>0:
                                    d["research_positive_full_convergence_scenarios"]=d.get(
                                       "research_positive_full_convergence_scenarios",0)+1
                            append_research_sample(state,entry)
                        else:
                            d["research_book_unavailable"]=d.get("research_book_unavailable",0)+1
                    except Exception as ex:
                        d["research_book_error"]=d.get("research_book_error",0)+1
                allowed=(state["paused_reason"] is None and
                         len(state["positions"])<MAX_ACTIVE_PAIRS and
                         unmarked==0 and len(coins)>=5)
                active_venues={p[v] for p in state["positions"] for v in ("long","short")}
                active_coins={p["coin"] for p in state["positions"]}
                checked=0
                for gap,coin,buy,sell in seen:
                    if not allowed or checked>=a.max_book_checks:break
                    if buy in active_venues or sell in active_venues or coin in active_coins:
                        continue
                    key=(coin,buy,sell)
                    if time.monotonic()-last_checked.get(key,0)<CANDIDATE_COOLDOWN_S:
                        continue
                    last_checked[key]=time.monotonic()
                    checked+=1
                    try:
                        first=two_books(pool,venues,buy,sell,coin)
                        if first is None:
                            d["book_unavailable_or_skewed"]=d.get("book_unavailable_or_skewed",0)+1
                            continue
                        proposal,reason=entry_estimate(state,venues,buy,sell,coin,first)
                        if proposal is None:
                            d[reason]=d.get(reason,0)+1
                            continue
                        # Require second independent fresh sample; skip if gap
                        # disappears or falls below post-cost threshold.
                        time.sleep(CONFIRM_INTERVAL_S)
                        second=two_books(pool,venues,buy,sell,coin)
                        if second is None:
                            d["confirmation_book_missing"]=d.get("confirmation_book_missing",0)+1
                            continue
                        proposal2,reason2=entry_estimate(state,venues,buy,sell,coin,second)
                        if proposal2 is None:
                            d["confirmation_"+str(reason2)]=d.get("confirmation_"+str(reason2),0)+1
                            continue
                        state["book_validations"].append({"utc":utc(),"coin":coin,
                            "buy":buy,"sell":sell,"gross_gap_pct":proposal2["entry_gross_gap_pct"],
                            "full_convergence_scenario_usdt":proposal2["estimated_full_convergence_usdt"],
                            "notional_per_leg_usdt":proposal2["notional_per_leg_usdt"],
                            "both_exchange_book_timestamps":proposal2["books_timestamp_present"]})
                        state["book_validations"]=state["book_validations"][-40:]
                        # Also reject unverifiable source timestamps for
                        # automatic paper entries. Keep research record.
                        if not proposal2["books_timestamp_present"]:
                            d["missing_exchange_book_timestamps"]=d.get("missing_exchange_book_timestamps",0)+1
                            continue
                        pos=open_paper(state,proposal2,events_path)
                        print("🟢 PAPER OPEN",pos["coin"],buy,"LONG",sell,"SHORT",
                             f"gap {pos['entry_gross_gap_pct']:.3f}%",
                             f"margin {pos['margin_long']:.2f}/{pos['margin_short']:.2f}",
                             f"scenario {pos['estimated_full_convergence_usdt']:.2f}",flush=True)
                        d["opened_paper"]=d.get("opened_paper",0)+1
                        active_venues.update((buy,sell))
                        active_coins.add(coin)
                        if len(state["positions"])>=MAX_ACTIVE_PAIRS:break
                    except Exception as ex:
                        d["validation_errors"]=d.get("validation_errors",0)+1
                        print("⚠️ BOOK CHECK",coin,buy,sell,type(ex).__name__,str(ex)[:85],flush=True)
                state["cycles"]+=1
                save_json(state_path,state)
                current_keys={(p["long"],p["short"],p["coin"]) for p in state["positions"]}
                active_marks={k:v for k,v in marks.items() if k in current_keys}
                save_json(root/"summary.json",snapshot(state,unmarked,active_marks,len(coins)))
                if state["cycles"]%3==0:
                    print("📊",utc(),"cycle",state["cycles"],"ticker ideas",len(seen),
                          "books checked",checked,"open",len(state["positions"]),
                          "closed",state["closed"],"P&L",round(state["realized_net_usdt"],3),
                          "paused",state["paused_reason"],flush=True)
                rest=a.poll-(time.monotonic()-cycle_start)
                if rest>0 and not stop_requested:
                    time.sleep(rest)
    finally:
        # Unknown marked equity if any open positions at shutdown.
        save_json(state_path,state)
        save_json(root/"summary.json",snapshot(state,len(state["positions"]),{},len(coins)))
        event(events_path,"ENGINE_STOP",open_positions=len(state["positions"]),
              note="Open positions persist in state for next paper run; no automatic fill on shutdown")
        print("🏁 V7 stopped cleanly; paper state preserved. Real orders were never enabled.",flush=True)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--minutes",type=float,default=1440)
    parser.add_argument("--poll",type=float,default=25)
    parser.add_argument("--coins",type=int,default=100)
    parser.add_argument("--max-book-checks",type=int,default=3)
    parser.add_argument("--out",default="/root/sol-arb-paper-20-aggressive/multicoin-v7")
    a=parser.parse_args()
    if a.self_test:
        return self_test()
    if a.minutes<=0 or a.poll<10 or a.coins<10 or a.coins>300 or a.max_book_checks<1 or a.max_book_checks>8:
        parser.error("minutes>0, poll>=10 sec, coins 10..300, max-book-checks 1..8")
    run(a)

if __name__=="__main__":
    main()
