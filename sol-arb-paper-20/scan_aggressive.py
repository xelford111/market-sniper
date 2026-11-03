#!/usr/bin/env python3
"""Public-book SOL/USDT cross-exchange paper scan. No keys, no orders."""
import argparse, concurrent.futures as cf, datetime as dt, json, math, statistics, time
import urllib.request
from pathlib import Path
from collections import Counter

VENUES = [
("binance","https://api.binance.com/api/v3/depth?symbol=SOLUSDT&limit=5"),
("bybit","https://api.bybit.com/v5/market/orderbook?category=spot&symbol=SOLUSDT&limit=5"),
("okx","https://www.okx.com/api/v5/market/books?instId=SOL-USDT&sz=5"),
("kraken","https://api.kraken.com/0/public/Depth?pair=SOLUSDT&count=5"),
("kucoin","https://api.kucoin.com/api/v1/market/orderbook/level2_20?symbol=SOL-USDT"),
("gate","https://api.gateio.ws/api/v4/spot/order_book?currency_pair=SOL_USDT&limit=5"),
("bitget","https://api.bitget.com/api/v2/spot/market/orderbook?symbol=SOLUSDT&type=step0&limit=5"),
("mexc","https://api.mexc.com/api/v3/depth?symbol=SOLUSDT&limit=5"),
("htx","https://api.huobi.pro/market/depth?symbol=solusdt&type=step0"),
("cryptocom","https://api.crypto.com/exchange/v1/public/get-book?instrument_name=SOL_USDT&depth=10"),
("coinbase","https://api.exchange.coinbase.com/products/SOL-USDT/book?level=2"),
("bitfinex","https://api-pub.bitfinex.com/v2/book/tSOLUST/P0?len=25"),
("bingx","https://open-api.bingx.com/openApi/spot/v1/market/depth?symbol=SOL-USDT&limit=5"),
("phemex","https://api.phemex.com/md/orderbook?symbol=sSOLUSDT"),
("coinex","https://api.coinex.com/v2/spot/depth?market=SOLUSDT&limit=5&interval=0"),
("whitebit","https://whitebit.com/api/v4/public/orderbook/SOL_USDT?limit=5"),
("lbank","https://api.lbkex.com/v2/depth.do?symbol=sol_usdt&size=5"),
("poloniex","https://api.poloniex.com/markets/SOL_USDT/orderBook?limit=5"),
("ascendex","https://ascendex.com/api/pro/v1/depth?symbol=SOL%2FUSDT"),
("xt","https://sapi.xt.com/v4/public/depth?symbol=sol_usdt&limit=5")
]
FUNDED = set(name for name,url in VENUES[:10])
FEE, SLIPPAGE, RESERVE, MIN_EDGE = 0.001, 0.0005, 0.0005, 0.001
AGGRESSIVE_FRACTION = 0.80  # Spend up to 80% of venue-side free inventory
MIN_ORDER_USDT = 15.0  # Skip economically meaningless fills

def unpack(name,obj):
    if name=="bybit": x=obj["result"]; return x["b"],x["a"]
    if name=="okx": x=obj["data"][0]; return x["bids"],x["asks"]
    if name=="kraken":
        if obj.get("error"): raise ValueError(str(obj["error"]))
        x=next(iter(obj["result"].values())); return x["bids"],x["asks"]
    if name in ("kucoin","bitget","lbank","xt"):
        x=obj["data"]; return x["bids"],x["asks"]
    if name=="htx": x=obj["tick"]; return x["bids"],x["asks"]
    if name=="cryptocom": x=obj["result"]["data"][0]; return x["bids"],x["asks"]
    if name=="bitfinex":
        return [[p,abs(v)] for p,n,v in obj if v>0],[[p,abs(v)] for p,n,v in obj if v<0]
    if name=="phemex": x=obj["result"]["book"]; return x["bids"],x["asks"]
    if name=="coinex":
        x=obj["data"]; x=x.get("depth",x); return x["bids"],x["asks"]
    if name=="ascendex": x=obj["data"]["data"]; return x["bids"],x["asks"]
    return obj["bids"],obj["asks"]

def clean(a):
    if isinstance(a,dict): a=list(a.items())
    levels=[]
    for v in a:
        if isinstance(v,dict):
            p=v.get("price",v.get("p"))
            q=v.get("amount",v.get("size",v.get("quantity",v.get("q"))))
        else: p,q=v[:2]
        p,q=float(p),float(q)
        if p>0 and q>0 and math.isfinite(p) and math.isfinite(q):levels.append((p,q))
    return levels

def fetch(pair):
    name,url=pair
    start=time.monotonic()
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"sol-arb-paper/1.0","Accept":"application/json"})
        with urllib.request.urlopen(req,timeout=4) as response:
            data=json.loads(response.read(180000))
        b,a=unpack(name,data)
        b=sorted(clean(b),reverse=True)
        a=sorted(clean(a))
        if not b or not a or b[0][0]>=a[0][0]:raise ValueError("invalid book")
        now=time.monotonic()
        return {"name":name,"b":b,"a":a,"ts":now,"latency":round(now-start,3)}
    except Exception as exc:
        return {"name":name,"error":type(exc).__name__+": "+str(exc)[:90]}

def vwap(levels,q):
    left=q
    cost=0
    for p,avail in levels:
        take=min(left,avail);cost+=p*take;left-=take
        if left<=1e-10:return cost/q
    return None

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--minutes",type=float,default=60)
    parser.add_argument("--poll",type=float,default=10)
    args=parser.parse_args()
    if args.minutes<=0 or args.poll<5:parser.error("minutes > 0 and poll >= 5 required")
    root=Path("/root/sol-arb-paper-20-aggressive");root.mkdir(parents=True,exist_ok=True)
    quotes=open(root/"quotes.jsonl","w",buffering=1)
    trades=open(root/"trades.jsonl","w",buffering=1)
    start=time.monotonic();loops=0;pnl=0.;wallets=None
    seen=set();fails=Counter();counts=Counter();cooldowns={}
    first_price=None;last_price=None
    print("AGGRESSIVE PAPER ONLY | 20 monitored | 10 funded at $500 | dynamic up-to-80%-inventory sizing | no real orders",flush=True)
    try:
        with cf.ThreadPoolExecutor(max_workers=20) as pool:
            while time.monotonic()-start<args.minutes*60:
                tick=time.monotonic()
                results=list(pool.map(fetch,VENUES))
                good=[r for r in results if "error" not in r]
                for r in results:
                    if "error" in r:fails[r["name"]]+=1
                    else:seen.add(r["name"]);counts[r["name"]]+=1
                if good:
                    mark=statistics.median([(r["b"][0][0]+r["a"][0][0])/2 for r in good])
                    good=[r for r in good if abs((r["b"][0][0]+r["a"][0][0])/2/mark-1)<0.025]
                    last_price=mark
                    if wallets is None and len(good)>=2:
                        first_price=mark
                        wallets={x:{"usdt":250.0,"sol":250.0/mark} for x in FUNDED}
                loops+=1
                now=dt.datetime.now(dt.timezone.utc).isoformat()
                quotes.write(json.dumps({"utc":now,"quotes":[{"exchange":r["name"],"bid":r["b"][0][0],"ask":r["a"][0][0],"funded":r["name"] in FUNDED} for r in good]})+"\n")
                opts=[]
                if wallets:
                    for buy in good:
                        if buy["name"] not in FUNDED:continue
                        for sell in good:
                            if sell["name"]==buy["name"] or sell["name"] not in FUNDED:continue
                            route=(buy["name"],sell["name"])
                            if abs(buy["ts"]-sell["ts"])>1.5:continue
                            if time.monotonic()-cooldowns.get(route,-9999)<60:continue
                            # Recalculate from current wallet inventories on EVERY quote.
                            # Initial target ~= $200, and can scale up as balances grow.
                            buy_balance=wallets[buy["name"]]["usdt"]
                            sell_inventory_sol=wallets[sell["name"]]["sol"]
                            notional=min(
                                buy_balance*AGGRESSIVE_FRACTION/(1+FEE+SLIPPAGE),
                                sell_inventory_sol*sell["b"][0][0]*AGGRESSIVE_FRACTION
                            )
                            if notional<MIN_ORDER_USDT:continue
                            quantity=notional/buy["a"][0][0]
                            bp=vwap(buy["a"],quantity);sp=vwap(sell["b"],quantity)
                            if bp is None or sp is None:continue
                            buy_cost=quantity*bp*(1+FEE+SLIPPAGE)
                            sell_cash=quantity*sp*(1-FEE-SLIPPAGE)
                            reserve=notional*RESERVE
                            net=sell_cash-buy_cost-reserve
                            if net<notional*MIN_EDGE:continue
                            if buy_balance<buy_cost or sell_inventory_sol<quantity:continue
                            if wallets[sell["name"]]["usdt"]+sell_cash<reserve:continue
                            opts.append((net,buy,sell,quantity,buy_cost,sell_cash,reserve,notional))
                if opts:
                    net,buy,sell,quantity,buy_cost,sell_cash,reserve,notional=max(opts,key=lambda x:x[0])
                    wallets[buy["name"]]["usdt"]-=buy_cost
                    wallets[buy["name"]]["sol"]+=quantity
                    wallets[sell["name"]]["sol"]-=quantity
                    wallets[sell["name"]]["usdt"]+=sell_cash-reserve
                    cooldowns[(buy["name"],sell["name"])]=time.monotonic()
                    pnl+=net
                    counts["trades"]+=1
                    trades.write(json.dumps({"utc":now,"buy":buy["name"],"sell":sell["name"],"trade_notional_usdt":round(notional,2),"net_arbitrage_usdt":round(net,5),"quantity_sol":quantity,"reserve_paid_usdt":round(reserve,4),"buy_cost_usdt":round(buy_cost,4),"sell_proceeds_usdt":round(sell_cash,4)})+"\n")
                if loops%6==0:
                    print("sweeps",loops,"responding",len(good),"paper_trades",counts["trades"],"est_arb_pnl_usdt",round(pnl,4),flush=True)
                time.sleep(max(0,args.poll-(time.monotonic()-tick)))
    except KeyboardInterrupt:
        print("Interrupted. Saving report.",flush=True)
    finally:
        equity=sum(w["usdt"]+w["sol"]*last_price for w in wallets.values()) if wallets and last_price else None
        summary={"date_utc":dt.datetime.now(dt.timezone.utc).isoformat(),"minutes":round((time.monotonic()-start)/60,2),"starting_balance_usdt":5000,"sizing":"80% of free USD on buy venue and 80% of SOL inventory on sell venue; dynamic, compounded; initial ~$200","note":"Inventory is not automatically rebalanced or transferred. A venue may run out of an asset even when total paper equity is positive.","funded_exchanges":sorted(FUNDED),"responding_exchanges":sorted(seen),"scan_count":loops,"paper_trades":counts["trades"],"estimated_arbitrage_pnl_usdt":round(pnl,4),"ending_equity_usdt":round(equity,4) if equity else None,"equity_change_usdt":round(equity-5000,4) if equity else None,"failed_requests":dict(fails),"successful_requests":{k:v for k,v in counts.items() if k!="trades"},"warning":"Indicative paper simulation only: asynchronous REST quotes; unverified fillability; assumed fees/slippage/rebalancing; SOL exposure changes marked equity independently of arbitrage profits. Rebalance reserve is deducted from simulated cash, but real exchange transfer delays/costs remain unmodeled."}
        (root/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
        print("RESULT",json.dumps(summary,indent=2),flush=True)
        quotes.close();trades.close()
if __name__=="__main__":main()
