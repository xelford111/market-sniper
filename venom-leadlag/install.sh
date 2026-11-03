#!/usr/bin/env bash
# Deploy only the independent paper lead-lag service on a DigitalOcean Ubuntu host.
# Never stops VENOM, SpotX or arbitrage, never takes an exchange API credential.
set -euo pipefail
APP=/root/venom-leadlag-paper
RAW=https://raw.githubusercontent.com/xelford111/market-sniper/feature/venom-leadlag-paper-20261103/venom-leadlag
mkdir -p "$APP"
echo "=== Download new LEAD-LAG engine only ==="
curl -fLsS --retry 3 "$RAW/leadlag_paper.py" -o "$APP/leadlag_paper.py.new"
curl -fLsS --retry 3 "$RAW/test_leadlag.py" -o "$APP/test_leadlag.py.new"
test -d "$APP/venv" || python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install --quiet 'aiohttp>=3.11,<4'
"$APP/venv/bin/python" -m py_compile "$APP/leadlag_paper.py.new" "$APP/test_leadlag.py.new"
mv "$APP/leadlag_paper.py.new" "$APP/leadlag_paper.py"
mv "$APP/test_leadlag.py.new" "$APP/test_leadlag.py"
"$APP/venv/bin/python" "$APP/test_leadlag.py"

echo "=== Install isolated paper service (no other services modified) ==="
cat >/etc/systemd/system/venom-leadlag-paper.service <<'SERVICE'
[Unit]
Description=Venom Lead-Lag Binance OKX signals and Bybit paper-only engine
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/root/venom-leadlag-paper
ExecStart=/root/venom-leadlag-paper/venv/bin/python -u /root/venom-leadlag-paper/leadlag_paper.py --output /root/venom-leadlag-paper --host 127.0.0.1 --port 8788 --start 1000 --leverage 5 --margin-fraction 0.2 --minutes 1440
Restart=always
RestartSec=10
Nice=15
NoNewPrivileges=true
PrivateTmp=true
LimitNOFILE=4096
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SERVICE
systemctl daemon-reload
systemctl enable --now venom-leadlag-paper.service

echo "=== Try separate HTTPS READ-ONLY Caddy hostname ==="
DOMAIN=leadlag.152-42-181-163.sslip.io
if command -v caddy >/dev/null 2>&1 && test -f /etc/caddy/Caddyfile; then
  # Back up before any additive change. Never alter another route.
  COPY=/etc/caddy/Caddyfile.backup-before-leadlag.$(date -u +%Y%m%dT%H%M%SZ)
  cp -p /etc/caddy/Caddyfile "$COPY"
  if ! grep -Fq "$DOMAIN {" /etc/caddy/Caddyfile; then
    cat >>/etc/caddy/Caddyfile <<EOF

# Separate read-only lead-lag paper output. No account credentials / trade endpoints.
$DOMAIN {
    @public path /api/leadlag/public /healthz
    handle @public {
        reverse_proxy 127.0.0.1:8788
    }
    handle {
        respond "Not Found" 404
    }
}
EOF
    if caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile; then
      if ! systemctl reload caddy; then
        echo "WARNING: Caddy reload failed; restoring previous file."
        cp -p "$COPY" /etc/caddy/Caddyfile
        systemctl reload caddy || true
      fi
    else
      echo "WARNING: Caddy configuration invalid; reverting addition."
      cp -p "$COPY" /etc/caddy/Caddyfile
    fi
  else
    echo "Caddy hostname already present; not changing the existing route."
  fi
else
  echo "Caddy not found; loopback API works but external HTTPS read URL needs setup."
fi

echo "=== Check NEW service only ==="
systemctl --no-pager --full status venom-leadlag-paper.service | head -n 16 || true
echo "=== Local paper API health ==="
for i in $(seq 1 10); do
  if curl -fsS --max-time 2 http://127.0.0.1:8788/healthz; then
    echo;break
  fi
  sleep 2
done
echo "=== Last paper engine log ==="
journalctl -u venom-leadlag-paper.service --no-pager -n 18 || true
echo "Local JSON: http://127.0.0.1:8788/api/leadlag/public"
echo "HTTPS JSON (once DNS and certificate active): https://$DOMAIN/api/leadlag/public"
echo "NO exchange credentials or real trade placement enabled."
