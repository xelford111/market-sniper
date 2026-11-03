# VENOM Lead-Lag V1 — Paper Research

Independent from SpotX, original VENOM SOL and multi-exchange arbitrage.

## Feeds and capital
- Binance USD-M public futures WebSocket: signal feed
- OKX USDT-SWAP public WebSocket: confirmation signal feed
- Bybit USDT linear perpetual public WebSocket: paper execution quotes
- One simulated Bybit wallet: 1,000 USDT, 5x, max 20% current available margin
- Symbols: BTCUSDT, ETHUSDT, SOLUSDT
- No API keys, no exchange account access, no real orders.

## Deploy on DigitalOcean (root shell)
```bash
curl -fLsS --retry 3 'https://raw.githubusercontent.com/xelford111/market-sniper/feature/venom-leadlag-paper-20261103/venom-leadlag/install.sh' -o /root/install_venom_leadlag.sh
bash /root/install_venom_leadlag.sh
```

## Inspect
```bash
systemctl status venom-leadlag-paper.service
journalctl -u venom-leadlag-paper.service --no-pager -n 35
curl -fsS http://127.0.0.1:8788/healthz
curl -fsS http://127.0.0.1:8788/api/leadlag/public
```

Once the independent Caddy domain and certificate are ready:
https://leadlag.152-42-181-163.sslip.io/api/leadlag/public

## Interpretation
The detector compares approximately synchronous price RETURNS on Binance and OKX
against Bybit; it does not assume that Binance always leads. It captures
forward price results at 2s, 5s and 10s and models two taker fees and
extra slippage. Signals are not validated profit opportunities.

New paper entries need same-direction movement at BOTH reference exchanges,
fresh source timestamps, sufficient Bybit visible top-level liquidity,
and a theoretical catch-up greater than estimated costs.

A 25 USDT stop is an intended paper mark threshold, NOT a guaranteed loss cap.
Actual funding, exchange restrictions, partial fills, liquidation, latency
and long out-of-sample performance have not been validated.

## Lovable
DEMO and PAPER are explicitly separate. PAPER polls read-only JSON only,
with an offline state until the droplet is deployed. The orb shows the
Bybit simulated account, not the fake combined demo wallets. The green and
red beams represent long and short paper events, not profitable or losing.

## Isolation
The installer creates only venom-leadlag-paper.service; no existing bot
service is stopped. It may add one new Caddy hostname after backing up
and validating the existing Caddyfile, then reload Caddy.
Anyone with the public URL can see simulated performance; it contains
no real account information or credentials.
