#!/usr/bin/env bash
# Recover only the newly installed VENOM LEAD-LAG paper service.
# Never kill the existing listener on 8788 or stop any other trading bot.
set -Eeuo pipefail
UNIT=venom-leadlag-paper.service
SERVICE=/etc/systemd/system/venom-leadlag-paper.service
CADDY=/etc/caddy/Caddyfile
DOMAIN=leadlag.152-42-181-163.sslip.io

if [[ "$(id -u)" != "0" ]]; then
  echo "ERROR: run as root on the droplet"; exit 1
fi
if [[ ! -f "$SERVICE" ]] || ! grep -Fq '/root/venom-leadlag-paper/leadlag_paper.py' "$SERVICE"; then
  echo "ERROR: dedicated lead-lag systemd service not found; not editing"; exit 1
fi
if [[ ! -f "$CADDY" ]] || ! grep -Fq "$DOMAIN {" "$CADDY"; then
  echo "ERROR: dedicated lead-lag Caddy hostname not found; not editing"; exit 1
fi

echo '=== Existing 8788 owner, read-only ==='
ss -ltnp '( sport = :8788 )' || true
echo '=== Existing 8788 HTTP response, read-only ==='
curl --noproxy '*' -sS --max-time 3 -i http://127.0.0.1:8788/healthz | head -n 8 || true

# Only the lead-lag unit is stopped.
systemctl stop "$UNIT" || true
PORT="$(python3 - <<'PY'
import socket
for port in (8798,8799,8808,8818,8828,8838):
    sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1",port))
    except OSError:
        sock.close()
        continue
    sock.close()
    print(port)
    break
else:
    raise SystemExit("ERROR: no free candidate port, no configuration edits")
PY
)"
echo "Selected unused local port: $PORT"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
S_BACKUP="$SERVICE.before-port-fix-$STAMP"
C_BACKUP="$CADDY.before-port-fix-$STAMP"
cp -p "$SERVICE" "$S_BACKUP"
cp -p "$CADDY" "$C_BACKUP"

echo '=== Update only the dedicated paper service and its own Caddy hostname ==='
PORT="$PORT" SERVICE="$SERVICE" CADDY="$CADDY" DOMAIN="$DOMAIN" python3 - <<'PY'
from pathlib import Path
import os,re
port=os.environ["PORT"]
service=Path(os.environ["SERVICE"])
caddy=Path(os.environ["CADDY"])
domain=os.environ["DOMAIN"]
unit=service.read_text()
matches=list(re.finditer(r"(?<!\S)--port\s+\d+",unit))
if len(matches)!=1:
    raise SystemExit("ERROR: paper service port ambiguous, refusing edit")
config=caddy.read_text()
anchor=f"{domain} {{"
if config.count(anchor)!=1:
    raise SystemExit("ERROR: Caddy hostname ambiguous, refusing edit")
begin=config.index("{",config.index(anchor))
depth=0
end=None
for i in range(begin,len(config)):
    if config[i]=="{":depth+=1
    elif config[i]=="}":
        depth-=1
        if depth==0:
            end=i+1
            break
if end is None:
    raise SystemExit("ERROR: dedicated Caddy block unbalanced")
block=config[config.index(anchor):end]
proxy=list(re.finditer(r"(?m)^(\s*reverse_proxy\s+)127\.0\.0\.1:(\d+)([ \t]*)$",block))
if len(proxy)!=1:
    raise SystemExit("ERROR: dedicated Caddy proxy ambiguous, refusing edit")
m=proxy[0]
updated=block[:m.start()]+m.group(1)+"127.0.0.1:"+port+m.group(3)+block[m.end():]
new_caddy=config[:config.index(anchor)]+updated+config[end:]
new_unit=unit[:matches[0].start()]+"--port "+port+unit[matches[0].end():]
service.write_text(new_unit)
caddy.write_text(new_caddy)
print("Moved dedicated service and dedicated Caddy upstream to",port)
PY

if ! caddy validate --config "$CADDY" --adapter caddyfile; then
  echo "Caddy validation failed, restoring backup files" >&2
  cp -p "$S_BACKUP" "$SERVICE"
  cp -p "$C_BACKUP" "$CADDY"
  systemctl daemon-reload
  exit 1
fi
systemctl daemon-reload
if ! systemctl restart "$UNIT"; then
  echo "New service restart failed, restoring files" >&2
  cp -p "$S_BACKUP" "$SERVICE"
  cp -p "$C_BACKUP" "$CADDY"
  systemctl daemon-reload
  exit 1
fi

echo '=== Verify ACTUAL new paper engine, not unrelated HTTP server ==='
OK=0
for _ in $(seq 1 12); do
  if curl --noproxy '*' -fsS --max-time 3 "http://127.0.0.1:$PORT/healthz" -o /tmp/venom-leadlag-health.json 2>/dev/null; then
    if python3 -c 'import json;d=json.load(open("/tmp/venom-leadlag-health.json"));assert d.get("paper_only") is True and d.get("version")=="venom-leadlag-paper-v1"' 2>/dev/null; then
      OK=1
      break
    fi
  fi
  sleep 2
done
if [[ "$OK" != "1" ]]; then
  echo "New paper service did not return matching health JSON. Restoring Caddy and stopping only lead-lag." >&2
  journalctl -u "$UNIT" --no-pager -n 25 || true
  systemctl stop "$UNIT" || true
  cp -p "$S_BACKUP" "$SERVICE"
  cp -p "$C_BACKUP" "$CADDY"
  systemctl daemon-reload
  exit 1
fi
echo '✅ Paper-only service /healthz verified'
cat /tmp/venom-leadlag-health.json
echo

if systemctl reload caddy; then
  echo '✅ Caddy reloaded (dedicated host proxy only)'
else
  echo '⚠️ Caddy reload failed, restoring Caddy file. Paper engine still running locally.'
  cp -p "$C_BACKUP" "$CADDY"
  systemctl reload caddy || true
fi
echo '=== Actual local paper status ==='
curl --noproxy '*' -fsS --max-time 5 "http://127.0.0.1:$PORT/api/leadlag/public" |
python3 -c 'import json,sys;d=json.load(sys.stdin);print("Version:",d.get("version"));print("Status:",d.get("status"));print("Feeds:",{k:(v.get("status"),v.get("count")) for k,v in d.get("market_feeds",{}).items()});print("Wallet:",d.get("wallet"));print("Mode:",d.get("mode"))'
echo '=== Public HTTPS check (TLS provisioning can take some time) ==='
if curl --noproxy '*' -fsS --max-time 12 "https://$DOMAIN/healthz"; then
  echo
  echo '✅ Public HTTPS is responding'
else
  echo '⚠️ Public HTTPS not ready; inspect: journalctl -u caddy -n 30 --no-pager'
fi
echo
echo '=== LEAD-LAG ONLY service ==='
systemctl --no-pager --full status "$UNIT" | head -n 16 || true
echo "Dedicated local API: http://127.0.0.1:$PORT/api/leadlag/public"
echo "Dedicated public API: https://$DOMAIN/api/leadlag/public"
echo 'Other trading services were not targeted.'
