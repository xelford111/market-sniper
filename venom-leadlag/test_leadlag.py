#!/usr/bin/env python3
"""Zero-network unit tests for public feed parsing, lead-lag math and paper accounting."""
import asyncio
import json
import math
import tempfile
import time
from pathlib import Path
import importlib.util

ROOT=Path(__file__).parent
spec=importlib.util.spec_from_file_location("leadlag_paper",ROOT/"leadlag_paper.py")
ll=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ll)

def q(mid,ts,mono,bid_qty=100.0,ask_qty=100.0):
    return {"mid":mid,"bid":mid-0.01,"ask":mid+0.01,
            "bid_qty":bid_qty,"ask_qty":ask_qty,"source_ms":ts,
            "seen_mono":mono}

def test_parser():
    now=time.time()
    ms=int(now*1000)
    binance={"data":{"e":"bookTicker","s":"BTCUSDT","E":ms,
                    "b":"100","a":"100.01","B":"20","A":"30"}}
    okx={"arg":{"channel":"books5","instId":"BTC-USDT-SWAP"},
         "data":[{"instId":"BTC-USDT-SWAP","ts":str(ms),
                  "bids":[["100","100","0","1"]],"asks":[["100.01","110","0","1"]]}]}
    bybit={"topic":"orderbook.1.BTCUSDT","type":"snapshot","ts":ms,
           "data":{"s":"BTCUSDT","b":[["100","25"]],"a":[["100.01","30"]]}}
    for venue,payload in (("binance",binance),("okx",okx),("bybit",bybit)):
        got=ll.parse_quote(venue,payload,now,10)
        assert got and got["symbol"]=="BTCUSDT", (venue,got)
        assert got["mid"]>100,got
    assert ll.parse_quote("binance",binance,now+10,10) is None
    assert ll.parse_quote("bybit",dict(bybit,type="delta"),now,10) is None
    assert ll.parse_quote("okx",{"arg":{"channel":"books5","instId":"BTC-USDT-SWAP"},
          "data":[{"ts":str(ms),"bids":[],"asks":[]}]},now,10) is None
    print("✅ Public exchange parser tests passed")

def test_signal():
    now=100.0
    stamp=now*1000
    hist={}
    quoted={}
    for venue,move in (("binance",0.005),("okx",0.0048),("bybit",0.0005)):
        hist[(venue,"BTCUSDT")]=[(98.0,100)]
        quoted[(venue,"BTCUSDT")]=q(100*(1+move),stamp,99.9)
    s=ll.compute_signal(hist,quoted,"BTCUSDT",now)
    assert s and s["direction"]=="LONG" and s["lag_gap_bps"]>40, s
    assert s["leaders_agree"] and s["reference_age_ms"]<200
    quoted[("okx","BTCUSDT")]=q(99.6,stamp,99.9)
    assert ll.compute_signal(hist,quoted,"BTCUSDT",now) is None
    quoted[("okx","BTCUSDT")]=q(100.48,stamp-8000,99.9)
    assert ll.compute_signal(hist,quoted,"BTCUSDT",now) is None
    print("✅ Agreement, lag-direction, stale-source and lookback tests passed")

def test_near_misses():
    now=100.0
    stamp=now*1000
    hist={}
    quoted={}
    for venue,move in (("binance",0.001),("okx",0.0009),("bybit",0.0001)):
        hist[(venue,"BTCUSDT")]=[(98.0,100)]
        quoted[(venue,"BTCUSDT")]=q(100*(1+move),stamp,99.9)
    row=ll.near_miss_observation(hist,quoted,"BTCUSDT",now)
    assert row and row["reason"]=="LEADER_BELOW_12BPS",row
    assert 8<row["lag_gap_bps"]<10
    assert row["minimum_net_hurdle_lag_bps"]==45
    assert row["estimated_gap_to_net_hurdle_bps"]>35
    # If we have enough of a lag to pass the 15bps gate but not to
    # clear expected costs, the diagnostic should say so explicitly.
    quoted[("binance","BTCUSDT")]=q(100.45,stamp,99.9)
    quoted[("okx","BTCUSDT")]=q(100.40,stamp,99.9)
    quoted[("bybit","BTCUSDT")]=q(100.02,stamp,99.9)
    row=ll.near_miss_observation(hist,quoted,"BTCUSDT",now)
    assert row and row["reason"]=="ESTIMATED_NET_BELOW_3BPS",row
    assert 40<row["lag_gap_bps"]<42
    assert not ll.near_miss_observation(hist,quoted,"BTCUSDT",now+4)
    print("✅ Near-miss reasons, modeled gap hurdle and stale quote rejection passed")

def test_wallet():
    with tempfile.TemporaryDirectory() as root:
        e=ll.Engine(root,1000,5,0.2)
        sig={"direction":"LONG","symbol":"BTCUSDT","lag_gap_bps":50}
        q={"bid":99.99,"ask":100.0,"bid_qty":200,
           "ask_qty":200,"mid":99.995,"source_ms":1,
           "seen_mono":1}
        assert e._open(sig,q)
        assert e.position is not None
        p=e.position.copy()
        assert p["margin"]<=200.01 and p["notional"]<=1001
        assert e.available<1000
        worse={**q,"bid":99.9}
        marked=ll.costed_exit(p,worse)
        assert marked["net"]<0
        e._close(worse,"TEST_CLOSE")
        assert e.position is None and e.completed==1
        assert abs((e.available-1000)-e.realized)<1e-6
        assert e.wins+e.losses==1
        e._persist()
        revived=ll.Engine(root,1000,5,0.2)
        assert revived.completed==1 and abs(revived.available-e.available)<1e-9
        assert revived.position is None
        try:ll.Engine(root,5000,5,0.2)
        except RuntimeError:pass
        else:raise AssertionError("State incompatibility must fail closed")
    print("✅ Margin, PnL conservation, state restore, and mismatched state rejection passed")

def test_studies():
    with tempfile.TemporaryDirectory() as root:
        e=ll.Engine(root,1000,5,0.2)
        now=time.monotonic()
        bq={"bid":100.0,"ask":100.1,"bid_qty":100,
            "ask_qty":100,"mid":100.05,"source_ms":time.time()*1000,
            "seen_mono":now}
        sig={"symbol":"SOLUSDT","direction":"LONG","lag_gap_bps":35}
        e._study(sig,bq)
        assert e.raw_candidates==1 and len(e.study_pending)==1
        task=e.study_pending[0]
        task["start"]-=11
        e.quotes[("bybit","SOLUSDT")]=bq
        e._resolve_studies(now)
        assert e.studies and e.studies[-1]["net_bps_10s"] is not None
        stats=e.research_stats()
        assert stats["observations"]==1 and not stats["out_of_sample_validated"]
    print("✅ Timestamped forward-study and explicit no-validation flag passed")

def main():
    test_parser()
    test_signal()
    test_near_misses()
    test_wallet()
    test_studies()
    print("🟢 ALL VENOM LEAD-LAG V1 OFFLINE TESTS PASSED; no real exchange orders possible.")

if __name__=="__main__":
    main()
