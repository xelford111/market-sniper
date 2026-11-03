#!/usr/bin/env bash
# Install V7 as a SEPARATE paper engine. Run as root on the DigitalOcean droplet.
# Existing VENOM and SpotX services are NEVER targeted by default.
# Optional: SPOTX_PAUSE=1 sh this_script to pause narrowly matched SpotX bots.
set -euo pipefail

DIR=/root/sol-arb-paper-20-aggressive
REPO=https://raw.githubusercontent.com/xelford111/market-sniper/paper-sol-arb-20-venue-20261103/sol-arb-paper-20
mkdir -p "$DIR"
echo '=== V7: verified Python files ==='
curl -fLsS --retry 3 "$REPO/arb_v7_paper.py" -o "$DIR/arb_v7_paper.py.new"
curl -fLsS --retry 3 "$REPO/live_dashboard_v7.py" -o "$DIR/live_dashboard_v7.py.new"
if ! test -x "$DIR/venv/bin/python"; then
    echo 'Missing existing paper Python virtual environment'; exit 1
fi
"$DIR/venv/bin/python" -c "import ccxt; print('CCXT ready',ccxt.__version__)"
"$DIR/venv/bin/python" -m py_compile "$DIR/arb_v7_paper.py.new" "$DIR/live_dashboard_v7.py.new"
"$DIR/venv/bin/python" "$DIR/arb_v7_paper.py.new" --self-test
mv "$DIR/arb_v7_paper.py.new" "$DIR/arb_v7_paper.py"
mv "$DIR/live_dashboard_v7.py.new" "$DIR/live_dashboard_v7.py"

if test "${SPOTX_PAUSE:-0}" = "1"; then
    echo '=== Pausing only known SpotX trading process paths ==='
    python3 - <<'PY'
from pathlib import Path
import os,signal
for p in Path('/proc').iterdir():
    if not p.name.isdigit():continue
    pid=int(p.name)
    if pid in (os.getpid(),os.getppid()):continue
    try:
        args=[x.decode('utf-8','replace') for x in (p/'cmdline').read_bytes().split(b'\0') if x]
        if len(args)<2:continue
        prog=Path(args[0]).name.lower()
        if not any(x in prog for x in ('node','python')):continue
        if any(a.startswith('/root/spotx') or a.startswith('/opt/spotx') for a in args[1:]):
            print('SpotX trading process SIGINT:',pid,' '.join(args[:3]),flush=True)
            os.kill(pid,signal.SIGINT)
    except (FileNotFoundError,ProcessLookupError,PermissionError):pass
PY
    for unit in spotx-engine.service spotx-bot.service spotx-trader.service spotx-strategy.service; do
        if systemctl is-active --quiet "$unit" 2>/dev/null; then
            systemctl stop "$unit"
            echo "Paused SpotX trading service: $unit"
        fi
    done
    echo 'Any other SpotX processes must be reviewed separately.'
fi

echo '=== Stopping older arbitrage scanners ONLY ==='
for old in scan.py multicoin_v3.py multicoin_v4.py multicoin_v4_1.py multicoin_v5_aud1000.py arb_v7_paper.py; do
    pkill -INT -f "^$DIR/venv/bin/python -u $DIR/$old" || true
done
sleep 4
echo '=== Memory headroom ==='
free -h
echo '=== Starting forward-only paper V7 ==='
nohup nice -n 15 "$DIR/venv/bin/python" -u "$DIR/arb_v7_paper.py" \
    --minutes 1440 --poll 25 --coins 100 --max-book-checks 3 \
    > "$DIR/v7.log" 2>&1 &
echo $! > "$DIR/v7.pid"
sleep 3
tail -n 25 "$DIR/v7.log"
echo '=== Live read-only dashboard ==='
echo "python3 $DIR/live_dashboard_v7.py"
