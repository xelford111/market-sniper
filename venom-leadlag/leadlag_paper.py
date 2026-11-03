#!/usr/bin/env python3
"""VENOM LEAD-LAG V1 — forward, PUBLIC MARKET DATA and PAPER ONLY.

Binance USD-M and OKX USDT-SWAP are independent reference feeds.
Bybit linear USDT perpetual top-of-book is simulated execution.
No API keys, no private endpoints, no order placement, no account access.
Designed for a 1 GiB droplet: 3 public WS connections, 3 coins, small buffers.

This engine studies whether leader *returns* predict subsequent Bybit returns.
It does not presume that Binance leads. Exchange venue fees, fill priority,
actual slippage/funding, liquidation and network conditions remain uncertain.
"""
import argparse
import asyncio
import collections
import datetime as dt
import json
import math
import os
import signal
import time
from pathlib import Path

try:
    from aiohttp import web, ClientSession, WSMsgType, ClientTimeout, ClientWSTimeout
except ImportError as e:
    raise SystemExit("Install aiohttp: python3 -m pip install aiohttp>=3.9") from e

COINS=("BTC","ETH","SOL")
START_USDT=1000.0
LEVERAGE=5.0
MARGIN_FRACTION=0.20
TAKER_FEE=0.0006          # per fill; hypothetical
SLIP=0.0005               # per fill; conservative extra adverse slippage
FUNDING_RESERVE=0.0002    # extra hurdle, not actual funding debit
MAX_POSITION_LOSS=25.0    # intended trigger, NOT guaranteed maximum loss
MAX_SESSION_LOSS=75.0     # stop new entries on cumulative realized loss
MAX_HOLD_SECONDS=10.0
MAX_QUOTE_AGE_MS=2000.0
MAX_SOURCE_SKEW_MS=1250.0
MIN_BOOK_MULTIPLIER=2.0
STUDY_RET_THRESHOLD_BPS=5.0
LIVE_SIGNAL_MIN_MOVE_BPS=12.0
LEADER_LAG_GAP_BPS=15.0
MIN_EXPECTED_NET_BPS=3.0
CATCHUP_ASSUMPTION=0.60 # hypothetical only; not evidence
ENTRY_COOLDOWN_SECONDS=20
FEED_URLS={
  "binance":"wss://fstream.binance.com/public/stream?streams="+"/".join(
      f"{c.lower()}usdt@bookTicker" for c in COINS),
  "okx":"wss://ws.okx.com:8443/ws/v5/public",
  "bybit":"wss://stream.bybit.com/v5/public/linear",
}
VERSION="venom-leadlag-paper-v1"

def clock():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def good_float(x):
    try:
        x=float(x)
        return x if x>0 and math.isfinite(x) else None
    except (ValueError,TypeError):
        return None

def parse_quote(venue,payload,recv_wall=None,recv_mono=None):
    """Parse a PUBLIC top-of-book payload. Return (symbol,bid,ask,bid_qty,ask_qty,ts)."""
    recv_wall=recv_wall or time.time()
    recv_mono=recv_mono or time.monotonic()
    try:
        if venue=="binance":
            d=payload.get("data",payload)
            symbol=d.get("s")
            if not symbol or not symbol.endswith("USDT"):return None
            ts=d.get("E",d.get("T"))
            bid,ask=good_float(d.get("b")),good_float(d.get("a"))
            bidqty,askqty=good_float(d.get("B")),good_float(d.get("A"))
        elif venue=="okx":
            arg=payload.get("arg",{})
            if arg.get("channel")!="books5":return None
            items=payload.get("data")
            if not items:return None
            d=items[0]
            inst=d.get("instId",arg.get("instId",""))
            if not inst.endswith("-USDT-SWAP"):return None
            symbol=inst.split("-")[0]+"USDT"
            ts=d.get("ts")
            bids,asks=d.get("bids") or [],d.get("asks") or []
            if not bids or not asks:return None
            bid,ask=good_float(bids[0][0]),good_float(asks[0][0])
            # OKX size is in contracts, NOT base units. Never use to size Bybit.
            bidqty=askqty=None
        elif venue=="bybit":
            if payload.get("type")!="snapshot":return None
            if not str(payload.get("topic","")).startswith("orderbook.1."):return None
            d=payload.get("data") or {}
            symbol=d.get("s")
            bids,asks=d.get("b") or [],d.get("a") or []
            if not bids or not asks:return None
            bid,ask=good_float(bids[0][0]),good_float(asks[0][0])
            bidqty,askqty=good_float(bids[0][1]),good_float(asks[0][1])
            ts=payload.get("ts")
        else:return None
        if symbol not in {c+"USDT" for c in COINS}:return None
        if not bid or not ask or not bidqty and venue!="okx":return None
        if not askqty and venue!="okx":return None
        if bid>=ask or ts is None:return None
        ts=float(ts)
        # Timestamp quality matters; silence is never interpreted as freshness.
        age_ms=recv_wall*1000-ts
        if not (-1000<=age_ms<=MAX_QUOTE_AGE_MS):return None
        return {"symbol":symbol,"bid":bid,"ask":ask,
                "mid":(bid+ask)/2,"bid_qty":bidqty,"ask_qty":askqty,
                "source_ms":ts,"seen_mono":recv_mono,"seen_wall":recv_wall}
    except (KeyError,ValueError,TypeError,IndexError):
        return None

def historical_value(samples,lookback_s,now):
    # Return newest available sample AT LEAST lookback old but at most 1 sec older.
    options=[x for x in samples if lookback_s<=now-x[0]<=lookback_s+1.0]
    return options[-1][1] if options else None

def compute_signal(history,quotes,symbol,now,lookback_s=1.5):
    """Deterministic return lead-lag test; no future data used."""
    q={v:quotes.get((v,symbol)) for v in ("binance","okx","bybit")}
    if any(v is None for v in q.values()):return None
    if any((now-v["seen_mono"])*1000>MAX_QUOTE_AGE_MS for v in q.values()):
        return None
    if max(v["source_ms"] for v in q.values())-min(v["source_ms"] for v in q.values())>MAX_SOURCE_SKEW_MS:
        return None
    returns={}
    for v in q:
        prior=historical_value(history.get((v,symbol),()),lookback_s,now)
        if prior is None:return None
        returns[v]=10000*(q[v]["mid"]/prior-1)
    b,o,y=returns["binance"],returns["okx"],returns["bybit"]
    leader=(b+o)/2
    lag=leader-y
    # Both leader venues must agree on direction and have a real move.
    agreement=(b*o>0 and min(abs(b),abs(o))>=STUDY_RET_THRESHOLD_BPS)
    if not agreement:return None
    return {
      "symbol":symbol,"binance_return_bps":round(b,3),
      "okx_return_bps":round(o,3),"bybit_return_bps":round(y,3),
      "leader_return_bps":round(leader,3),
      "lag_gap_bps":round(lag,3),
      "direction":"LONG" if lag>0 else "SHORT",
      "leaders_agree":True,
      "reference_age_ms":round(max((now-q[v]["seen_mono"])*1000 for v in q),1),
      "cross_source_skew_ms":round(max(v["source_ms"] for v in q.values())-min(v["source_ms"] for v in q.values()),1)
    }

def expected_bps(sig):
    return abs(sig["lag_gap_bps"])*CATCHUP_ASSUMPTION - 2*(TAKER_FEE+SLIP)*10000 - FUNDING_RESERVE*10000


def near_miss_observation(history,quotes,symbol,now,lookback_s=1.5):
    """Explain entry-rule failures on synchronized, fresh public price RETURNS.

    Pure observation: no account changes or automatic parameter adjustments.
    A near miss here does NOT imply an actually profitable trade.
    """
    q={v:quotes.get((v,symbol)) for v in ("binance","okx","bybit")}
    if any(v is None for v in q.values()):return None
    if any(now-v["seen_mono"]<0 or (now-v["seen_mono"])*1000>MAX_QUOTE_AGE_MS
           for v in q.values()):return None
    skew=max(x["source_ms"] for x in q.values())-min(x["source_ms"] for x in q.values())
    if skew>MAX_SOURCE_SKEW_MS:return None
    returns={}
    for v in q:
        prior=historical_value(history.get((v,symbol),()),lookback_s,now)
        if prior is None:return None
        returns[v]=10000*(q[v]["mid"]/prior-1)
    b,o,y=returns["binance"],returns["okx"],returns["bybit"]
    leader=(b+o)/2
    lag=leader-y
    expected=abs(lag)*CATCHUP_ASSUMPTION-2*(TAKER_FEE+SLIP)*10000-FUNDING_RESERVE*10000
    agreement=b*o>0
    quiet=min(abs(b),abs(o))<STUDY_RET_THRESHOLD_BPS
    # A modest threshold excludes random sub-basis-point quote flicker.
    if abs(leader)<2.0 and abs(lag)<2.0:return None
    reason=None
    if not agreement:
        reason="LEADERS_DISAGREE"
    elif quiet:
        reason="LEADER_FEED_MOVE_BELOW_5BPS"
    elif abs(leader)<LIVE_SIGNAL_MIN_MOVE_BPS:
        reason="LEADER_BELOW_12BPS"
    elif abs(lag)<LEADER_LAG_GAP_BPS:
        reason="LAG_BELOW_15BPS"
    elif abs(y)>abs(leader)*0.6:
        reason="BYBIT_ALREADY_FOLLOWED"
    elif expected<MIN_EXPECTED_NET_BPS:
        reason="ESTIMATED_NET_BELOW_3BPS"
    else:
        reason="SIGNAL_THRESHOLDS_PASS" # Could still fail liquidity/cooldown.
    hurdle=(MIN_EXPECTED_NET_BPS+2*(TAKER_FEE+SLIP)*10000+
            FUNDING_RESERVE*10000)/CATCHUP_ASSUMPTION
    # Rank by absolute lag relative to the *actual modeled* profitability hurdle.
    # Reasons retain the first failing prerequisite (not just the gap).
    return {
        "timestamp":clock(),"symbol":symbol,
        "direction":"LONG" if lag>0 else "SHORT",
        "binance_move_bps":round(b,3),"okx_move_bps":round(o,3),
        "bybit_move_bps":round(y,3),
        "leader_move_bps":round(leader,3),
        "lag_gap_bps":round(lag,3),
        "lag_gap_pct":round(lag/100,5),
        "modeled_net_bps":round(expected,3),
        "estimated_gap_to_net_hurdle_bps":round(max(0,hurdle-abs(lag)),3),
        "minimum_net_hurdle_lag_bps":round(hurdle,3),
        "reason":reason,
        "reference_agreement":agreement,
        "source_skew_ms":round(skew,1),
        "note":"Signal proximity only, not a validated trade or predicted return."
    }

def costed_exit(position,bybit_quote):
    side=position["direction"]
    qty=position["qty"]
    mark=(bybit_quote["bid"]*(1-SLIP) if side=="LONG" else
          bybit_quote["ask"]*(1+SLIP))
    gross=qty*(mark-position["entry"]) if side=="LONG" else qty*(position["entry"]-mark)
    exit_fee=qty*mark*TAKER_FEE
    pnl=gross-position["entry_fee"]-exit_fee
    return {"gross":gross,"exit_fee":exit_fee,"net":pnl,"exit_price":mark}

class Engine:
    def __init__(self,root,start,leverage,margin_frac):
        self.root=Path(root)
        self.root.mkdir(parents=True,exist_ok=True)
        self.state_file=self.root/"state.json"
        self.events_file=self.root/"events.jsonl"
        self.start=start
        self.leverage=leverage
        self.margin_frac=margin_frac
        self.quotes={}
        self.hist=collections.defaultdict(lambda:collections.deque(maxlen=80))
        self.feed_stats={v:{"status":"CONNECTING","count":0,"error":None}
                         for v in ("binance","okx","bybit")}
        self.events=collections.deque(maxlen=30)
        self.signals=collections.deque(maxlen=20)
        self.near_misses=collections.deque(maxlen=120)
        self.last_near_miss={}
        self.raw_candidates=0
        self.entered=0
        self.completed=0
        self.wins=0
        self.losses=0
        self.realized=0.0
        self.available=start
        self.position=None
        self.last_entry={k:0.0 for k in (c+"USDT" for c in COINS)}
        self.last_study={}
        self.studies=collections.deque(maxlen=300)
        self.study_pending=[]
        self.entry_pause=None
        self.last_summary=None
        self.pulse_ts=0
        self.stop=False
        self._load()
    def _load(self):
        if not self.state_file.exists():return
        d=json.loads(self.state_file.read_text())
        if d.get("version")!=VERSION or d.get("initial_usdt")!=self.start:
            raise RuntimeError("Incompatible paper-state detected; refusing reset")
        self.available=d["available"]
        self.realized=d["realized"]
        self.completed=d["completed"]
        self.wins=d["wins"]
        self.losses=d["losses"]
        self.position=d.get("position")
        self.entry_pause=d.get("entry_pause")
        self.entered=d.get("entered",0)
        self.raw_candidates=d.get("raw_candidates",0)
        self.events=collections.deque(d.get("events",[]),maxlen=30)
        self.studies=collections.deque(d.get("studies",[]),maxlen=300)
        self.signals=collections.deque(d.get("signals",[]),maxlen=20)
        self.near_misses=collections.deque(d.get("near_misses",[]),maxlen=120)
    def _persist(self):
        data={"version":VERSION,"initial_usdt":self.start,
              "available":self.available,"realized":self.realized,
              "completed":self.completed,"wins":self.wins,"losses":self.losses,
              "position":self.position,"entry_pause":self.entry_pause,
              "entered":self.entered,"raw_candidates":self.raw_candidates,
              "events":list(self.events),"studies":list(self.studies)[-150:],
              "signals":list(self.signals),
              "near_misses":list(self.near_misses)[-120:]}
        tmp=self.state_file.with_suffix(".tmp")
        with tmp.open("w") as f:
            json.dump(data,f);f.flush();os.fsync(f.fileno())
        os.replace(tmp,self.state_file)
    def append(self,typ,**data):
        e={"id":f"{int(time.time()*1000)}-{os.getpid()}-{len(self.events)}",
           "timestamp":clock(),"type":typ,**data}
        self.events.append(e)
        with self.events_file.open("a") as f:
            f.write(json.dumps(e,separators=(",",":"))+"\n")
        print("📌",typ,e.get("symbol",""),e.get("direction",""),e.get("pnl_usdt",""),flush=True)
        return e
    async def watch(self,venue,session):
        retry=1
        while not self.stop:
            try:
                async with session.ws_connect(FEED_URLS[venue],heartbeat=15,
                        timeout=ClientWSTimeout(ws_receive=45,ws_close=10),
                        autoping=True) as ws:
                    self.feed_stats[venue]["status"]="CONNECTED"
                    self.feed_stats[venue]["error"]=None
                    retry=1
                    if venue=="okx":
                        await ws.send_json({"op":"subscribe","args":[
                          {"channel":"books5","instId":f"{c}-USDT-SWAP"} for c in COINS]})
                    if venue=="bybit":
                        await ws.send_json({"op":"subscribe","args":[
                            f"orderbook.1.{c}USDT" for c in COINS]})
                    async for msg in ws:
                        if self.stop:break
                        if msg.type==WSMsgType.TEXT:
                            try:
                                data=json.loads(msg.data)
                                q=parse_quote(venue,data)
                                if q:
                                    sym=q["symbol"]
                                    self.quotes[(venue,sym)]=q
                                    self.feed_stats[venue]["count"]+=1
                                    self.feed_stats[venue]["last_sample_utc"]=clock()
                                    self.feed_stats[venue]["last_source_ms"]=q["source_ms"]
                            except (ValueError,TypeError):
                                continue
                        elif msg.type in (WSMsgType.CLOSED,WSMsgType.ERROR):
                            break
                self.feed_stats[venue]["status"]="RECONNECTING"
            except Exception as ex:
                self.feed_stats[venue]["status"]="RECONNECTING"
                self.feed_stats[venue]["error"]=type(ex).__name__+":"+str(ex)[:140]
                print("⚠️ feed",venue,self.feed_stats[venue]["error"],flush=True)
            await asyncio.sleep(min(30,retry))
            retry=min(30,retry*2)
    def _good_q(self,venue,symbol,now):
        q=self.quotes.get((venue,symbol))
        return q if q and 0<=now-q["seen_mono"]<=MAX_QUOTE_AGE_MS/1000 else None
    def _fresh_feeds(self,symbol,now):
        q=[self._good_q(v,symbol,now) for v in ("binance","okx","bybit")]
        return (all(x is not None for x in q) and
                max(x["source_ms"] for x in q)-min(x["source_ms"] for x in q)<=MAX_SOURCE_SKEW_MS)
    def _open(self,sig,q):
        side=sig["direction"]
        margin=min(self.available*self.margin_frac,self.available/(1+TAKER_FEE*self.leverage+SLIP*self.leverage))
        entry_ref=q["ask"] if side=="LONG" else q["bid"]
        entry=entry_ref*(1+SLIP if side=="LONG" else 1-SLIP)
        qty=margin*self.leverage/entry
        depth=q["ask_qty"] if side=="LONG" else q["bid_qty"]
        if not depth or depth<qty*MIN_BOOK_MULTIPLIER:return False
        entry_fee=qty*entry*TAKER_FEE
        reserved=qty*entry/self.leverage
        if reserved+entry_fee>self.available:return False
        self.available-=reserved+entry_fee
        self.position={
            "symbol":sig["symbol"],"direction":side,"qty":qty,"entry":entry,
            "open_epoch":time.time(),"margin":reserved,"entry_fee":entry_fee,
            "signal_lag_bps":sig["lag_gap_bps"],"notional":qty*entry,
            "mark":None
        }
        self.entered+=1
        self.append("OPEN",symbol=sig["symbol"],direction=side,
            venue="Bybit",price=round(entry,8),qty=round(qty,8),
            notional_usdt=round(qty*entry,2),margin_usdt=round(reserved,2),
            signal=sig)
        return True
    def _close(self,q,reason):
        p=self.position
        if not p:return
        res=costed_exit(p,q)
        payout=max(0.0,p["margin"]+res["gross"]-res["exit_fee"])
        pnl=payout-p["margin"]-p["entry_fee"]
        self.available+=payout
        self.realized+=pnl
        self.completed+=1
        if pnl>0:self.wins+=1
        else:self.losses+=1
        self.position=None
        self.append("CLOSE",symbol=p["symbol"],direction=p["direction"],
            venue="Bybit",pnl_usdt=round(pnl,4),reason=reason,
            price=round(res["exit_price"],8),notional_usdt=round(p["notional"],2))
        if self.realized<=-MAX_SESSION_LOSS:self.entry_pause="MAX_REALIZED_LOSS"

    def _record_near_miss(self,symbol,now):
        """At most one sample per symbol every five seconds, bounded history."""
        if now-self.last_near_miss.get(symbol,0)<5.0:return
        row=near_miss_observation(self.hist,self.quotes,symbol,now)
        if row is None:return
        self.last_near_miss[symbol]=now
        # Actual qualification is unchanged. Near misses are evidence only.
        if row["reason"]=="SIGNAL_THRESHOLDS_PASS":return
        self.near_misses.append(row)

    def _study(self,sig,q):
        now=time.monotonic()
        sym=sig["symbol"]
        side=sig["direction"]
        key=(sym,side)
        if now-self.last_study.get(key,0)<4:return
        self.last_study[key]=now
        self.raw_candidates+=1
        open_px=q["ask"]*(1+SLIP) if side=="LONG" else q["bid"]*(1-SLIP)
        task={"symbol":sym,"direction":side,"recorded":clock(),
              "entry":open_px,"initial_lag_bps":sig["lag_gap_bps"],
              "start":now,"results":{}}
        self.study_pending.append(task)
    def _resolve_studies(self,now):
        for study in list(self.study_pending):
            for period in (2,5,10):
                if str(period) in study["results"] or now-study["start"]<period:continue
                q=self._good_q("bybit",study["symbol"],now)
                if not q:
                    study["results"][str(period)]=None
                    continue
                price=q["bid"]*(1-SLIP) if study["direction"]=="LONG" else q["ask"]*(1+SLIP)
                gross_bps=((price/study["entry"]-1)*10000 if study["direction"]=="LONG" else
                           (1-price/study["entry"])*10000)
                net_bps=gross_bps-TAKER_FEE*2*10000  # entry+exit fees
                study["results"][str(period)]=round(net_bps,3)
            if "10" in study["results"]:
                self.studies.append({
                    "symbol":study["symbol"],"direction":study["direction"],
                    "timestamp":study["recorded"],
                    "initial_lag_bps":round(study["initial_lag_bps"],2),
                    "net_bps_2s":study["results"].get("2"),
                    "net_bps_5s":study["results"].get("5"),
                    "net_bps_10s":study["results"].get("10"),
                    "note":"Hypothetical bid/ask study, not a live fill"})
                self.study_pending.remove(study)
    def research_stats(self):
        sample=[x["net_bps_5s"] for x in self.studies if x.get("net_bps_5s") is not None]
        return {"observations":len(sample),
                "positive_count":sum(x>0 for x in sample),
                "mean_net_bps_5s":round(sum(sample)/len(sample),3) if sample else None,
                "median_net_bps_5s":round(sorted(sample)[len(sample)//2],3) if sample else None,
                "out_of_sample_validated":False,
                "note":"Exploratory forward signal study, no trained model or independent holdout yet"}
    def tick(self):
        now=time.monotonic()
        nowwall=time.time()
        for c in COINS:
            symbol=c+"USDT"
            # Sample *fresh* quotes every 250ms. No synthetic interpolation.
            for v in ("binance","okx","bybit"):
                q=self._good_q(v,symbol,now)
                if q:
                    self.hist[(v,symbol)].append((now,q["mid"]))
        self._resolve_studies(now)
        # Read-only diagnostics run even while a simulated trade is active.
        for c in COINS:
            self._record_near_miss(c+"USDT",now)
        if self.position:
            p=self.position
            q=self._good_q("bybit",p["symbol"],now)
            if q:
                mark=costed_exit(p,q)
                p["mark"]=round(mark["net"],5)
                age=nowwall-p["open_epoch"]
                if mark["net"]<=-MAX_POSITION_LOSS:
                    self._close(q,"INTENDED_STOP")
                elif mark["net"]>=max(2.0,0.003*p["notional"]):
                    self._close(q,"NET_TAKE_PROFIT")
                elif age>=MAX_HOLD_SECONDS:
                    self._close(q,"TIME_EXIT")
            # If quote is stale, position remains open and new entries are frozen.
        if self.position or self.entry_pause:return
        for c in COINS:
            sym=c+"USDT"
            if not self._fresh_feeds(sym,now):continue
            sig=compute_signal(self.hist,self.quotes,sym,now)
            if not sig:continue
            if abs(sig["lag_gap_bps"])<STUDY_RET_THRESHOLD_BPS:continue
            q=self._good_q("bybit",sym,now)
            if q is None:continue
            self._study(sig,q)
            self.signals.append({"timestamp":clock(),**sig,
                "expected_net_bps_scenario":round(expected_bps(sig),3)})
            if now-self.last_entry[sym]<ENTRY_COOLDOWN_SECONDS:continue
            if abs(sig["leader_return_bps"])<LIVE_SIGNAL_MIN_MOVE_BPS:continue
            if abs(sig["lag_gap_bps"])<LEADER_LAG_GAP_BPS:continue
            if abs(sig["bybit_return_bps"])>abs(sig["leader_return_bps"])*0.6:
                continue
            if expected_bps(sig)<MIN_EXPECTED_NET_BPS:continue
            if self._open(sig,q):
                self.last_entry[sym]=now
                break
    def summary(self):
        now=time.monotonic()
        p=self.position
        unp=p["mark"] if p else 0.0
        equity=(self.available+p["margin"]+unp+p["entry_fee"]) if p and unp is not None else (
                self.available if not p else None)
        symbols=[]
        for c in COINS:
            s=c+"USDT"
            item={"symbol":s}
            for v in ("binance","okx","bybit"):
                q=self._good_q(v,s,now)
                item[v]=({"bid":round(q["bid"],8),"ask":round(q["ask"],8),
                          "source_age_ms":round((time.time()*1000-q["source_ms"]),0)}
                         if q else None)
            symbols.append(item)
        return {
            "version":VERSION,"timestamp":clock(),"mode":"paper",
            "strategy":"binance_okx_leadlag_bybit",
            "status":"ACTIVE" if any(all(item[v] is not None for v in ("binance","okx","bybit")) for item in symbols) else "WAITING_FOR_FEEDS",
            "wallet":{"venue":"Bybit","currency":"USDT","starting":self.start,
                 "available":round(self.available,3),
                 "reserved_margin":round(p["margin"],3) if p else 0.0,
                 "estimated_equity":round(equity,3) if equity is not None else None,
                 "realized_pnl":round(self.realized,3),
                 "unrealized_net_exit_pnl":round(unp,3) if unp is not None else None,
                 "leverage":self.leverage,
                 "max_margin_fraction":self.margin_frac},
            "market_feeds":self.feed_stats,
            "markets":symbols,
            "position":({"symbol":p["symbol"],"direction":p["direction"],
                         "notional_usdt":round(p["notional"],3),
                         "margin_usdt":round(p["margin"],3),
                         "entry":round(p["entry"],8),
                         "opened_epoch":p["open_epoch"],"unrealized_pnl":unp}
                        if p else None),
            "trades":{"opened":self.entered,"completed":self.completed,
                       "wins":self.wins,"losses":self.losses},
            "signals":list(self.signals)[-10:],
            "research":self.research_stats(),
            "recent_studies":list(self.studies)[-10:],
            "near_misses":sorted(
                [x for x in self.near_misses if time.time()-dt.datetime.fromisoformat(x["timestamp"]).timestamp()<3600],
                key=lambda x: (
                    x["reason"] not in ("LEADERS_DISAGREE","LEADER_FEED_MOVE_BELOW_5BPS"),
                    -x["estimated_gap_to_net_hurdle_bps"],
                    abs(x["lag_gap_bps"])),reverse=True)[:12],
            "near_miss_total_logged":len(self.near_misses),
            "events":list(self.events)[-20:],
            "entry_pause":self.entry_pause,
            "limitations":[
               "Market-data synchronization is approximate, not matching-engine atomic.",
               "No proof that Binance or OKX leads Bybit; signals require independent validation.",
               "5x paper fills and stop prices are assumed, not executable fills.",
               "No exchange fees tier, partial fill, funding cashflows or liquidation engine.",
               "$25 stop is an intended mark trigger, not a maximum actual loss.",
               "No API credentials, no real trading capability."
            ]
        }
    async def loop(self):
        print("🚀 VENOM LEAD-LAG V1 | Binance + OKX sensing / Bybit paper execution",flush=True)
        print("💰 Bybit paper wallet",self.start,"USDT |",self.leverage,"x | margin fraction",self.margin_frac,flush=True)
        print("🔒 READ-ONLY PUBLIC WEBSOCKETS. NO REAL ORDERS.",flush=True)
        lastsave=0.0
        while not self.stop:
            self.tick()
            now=time.monotonic()
            if now-lastsave>=2:
                self._persist()
                self.last_summary=self.summary()
                lastsave=now
                if int(now)%30<2:
                    print("📊",clock(),"feeds",{v:f["status"] for v,f in self.feed_stats.items()},
                          "research",len(self.studies),"opened",self.entered,
                          "closed",self.completed,"realized",round(self.realized,3),flush=True)
            await asyncio.sleep(0.25)

async def serve(engine,host,port):
    app=web.Application()
    async def public(request):
        d=engine.last_summary or engine.summary()
        return web.json_response(d,headers={"Cache-Control":"no-store",
                   "Access-Control-Allow-Origin":"*"})
    async def health(request):
        return web.json_response({"ok":True,"version":VERSION,"paper_only":True})
    app.router.add_get("/api/leadlag/public",public)
    app.router.add_get("/healthz",health)
    runner=web.AppRunner(app,access_log=None)
    await runner.setup()
    site=web.TCPSite(runner,host,port)
    await site.start()
    return runner

async def main(args):
    eng=Engine(args.output,args.start,args.leverage,args.margin_fraction)
    timeout=ClientTimeout(total=40)
    async with ClientSession(timeout=timeout,trust_env=False) as session:
        runner=await serve(eng,args.host,args.port)
        tasks=[asyncio.create_task(eng.watch(v,session),name=v) for v in FEED_URLS]
        tasks.append(asyncio.create_task(eng.loop(),name="engine"))
        start=time.monotonic()
        try:
            while time.monotonic()-start<args.minutes*60 and not eng.stop:
                await asyncio.sleep(1)
        finally:
            eng.stop=True
            for t in tasks:t.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            eng._persist()
            await runner.cleanup()
            print("🏁 lead-lag paper engine stopped. State kept; no orders placed.",flush=True)

def cli():
    p=argparse.ArgumentParser()
    p.add_argument("--output",default="/root/venom-leadlag-paper")
    p.add_argument("--host",default="127.0.0.1")
    p.add_argument("--port",type=int,default=8788)
    p.add_argument("--start",type=float,default=START_USDT)
    p.add_argument("--leverage",type=float,default=LEVERAGE)
    p.add_argument("--margin-fraction",type=float,default=MARGIN_FRACTION)
    p.add_argument("--minutes",type=float,default=1440)
    a=p.parse_args()
    if a.start<50 or not 1<=a.leverage<=10 or not 0.05<=a.margin_fraction<=0.5 or a.minutes<=0:
        p.error("Start≥50, leverage 1..10, margin 0.05..0.5, minutes>0")
    try:asyncio.run(main(a))
    except KeyboardInterrupt:pass

if __name__=="__main__":
    cli()
