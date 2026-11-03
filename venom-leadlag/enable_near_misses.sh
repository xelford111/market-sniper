#!/usr/bin/env bash
# Add near-miss diagnostics to the EXISTING standalone paper engine.
# Does not touch SpotX, VENOM SOL, arbitrage bots or exchange keys.
set -euo pipefail
ROOT=/root/venom-leadlag-paper
UNIT=venom-leadlag-paper.service
BASE=https://raw.githubusercontent.com/xelford111/market-sniper/feature/venom-leadlag-paper-20261103/venom-leadlag
PY="$ROOT/venv/bin/python"
test -x "$PY" || { echo "Missing paper Python environment"; exit 1; }
if ! systemctl cat "$UNIT" | grep -Fq "$ROOT/leadlag_paper.py"; then
  echo "Refusing update: unexpected service target"; exit 1
fi
echo "=== Download isolated near-miss monitor ==="
curl -fLsS --retry 3 "$BASE/leadlag_paper.py" -o "$ROOT/leadlag_paper.py.next"
curl -fLsS --retry 3 "$BASE/test_leadlag.py" -o "$ROOT/test_leadlag.py.next"
"$PY" -m py_compile "$ROOT/leadlag_paper.py.next" "$ROOT/test_leadlag.py.next"
cp -p "$ROOT/leadlag_paper.py" "$ROOT/leadlag_paper.py.before-near-misses.$(date -u +%Y%m%dT%H%M%SZ)"
mv "$ROOT/leadlag_paper.py.next" "$ROOT/leadlag_paper.py"
mv "$ROOT/test_leadlag.py.next" "$ROOT/test_leadlag.py"
"$PY" "$ROOT/test_leadlag.py"
echo "=== Restart dedicated paper engine ONLY; state file preserved ==="
systemctl restart "$UNIT"
echo "=== Verify near-miss status ==="
for i in $(seq 1 15); do
  if curl --noproxy '*' -fsS --max-time 2 http://127.0.0.1:8798/api/leadlag/public -o "$ROOT/near_miss_snapshot.json" 2>/dev/null; then
    if "$PY" - "$ROOT/near_miss_snapshot.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
assert d.get("version")=="venom-leadlag-paper-v1"
assert isinstance(d.get("near_misses"),list)
print("Status:",d.get("status"))
print("Near misses (last hour):",len(d["near_misses"]))
for s in d["near_misses"][:10]:
    print(f"{s['symbol']:<8} {s['direction']:<5} lag={s['lag_gap_bps']:+.2f}bps "
          f"gap to hurdle={s['estimated_gap_to_net_hurdle_bps']:.2f}bps "
          f"reason={s['reason']}")
PY
    then
      echo "✅ Near-miss recording available; no trade filters changed."
      exit 0
    fi
  fi
  sleep 2
done
echo "ERROR: New paper service not yet responding. Check: journalctl -u $UNIT -n 30 --no-pager" >&2
exit 1
