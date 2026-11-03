#!/usr/bin/env bash
# Upgrade V7 to V7.1 on the SAME five-wallet paper state.
# Narrow scope: only V7 engine process started by previous installer.
# VENOM, SpotX, and other processes are not targeted.
set -euo pipefail
DIR=/root/sol-arb-paper-20-aggressive
BASE=https://raw.githubusercontent.com/xelford111/market-sniper/paper-sol-arb-20-venue-20261103/sol-arb-paper-20
PY="$DIR/venv/bin/python"
test -x "$PY" || { echo "Missing paper venv at $PY"; exit 1; }
mkdir -p "$DIR"
echo "=== Download V7.1 paper-only monitor and dashboard ==="
curl -fLsS --retry 3 "$BASE/arb_v7_1_paper.py" -o "$DIR/arb_v7_1_paper.py.new"
curl -fLsS --retry 3 "$BASE/live_dashboard_v7_1.py" -o "$DIR/live_dashboard_v7_1.py.new"
"$PY" -m py_compile "$DIR/arb_v7_1_paper.py.new" "$DIR/live_dashboard_v7_1.py.new"
"$PY" "$DIR/arb_v7_1_paper.py.new" --self-test
mv "$DIR/arb_v7_1_paper.py.new" "$DIR/arb_v7_1_paper.py"
mv "$DIR/live_dashboard_v7_1.py.new" "$DIR/live_dashboard_v7_1.py"
echo "=== Back up paper trading state (if present) ==="
STATE="$DIR/multicoin-v7/state.json"
if test -f "$STATE"; then
    cp -p "$STATE" "$STATE.pre-v7.1.$(date -u +%Y%m%dT%H%M%SZ)"
fi

echo "=== Graceful V7-only stop (state preserved) ==="
PIDFILE="$DIR/v7.pid"
if test -f "$PIDFILE"; then
  OLD_PID="$(cat "$PIDFILE")"
  if [[ "$OLD_PID" =~ ^[0-9]+$ ]] && test -r "/proc/$OLD_PID/cmdline"; then
    CMD="$(tr '\0' ' ' < "/proc/$OLD_PID/cmdline")"
    case "$CMD" in
      *"$DIR/arb_v7_paper.py"*|*"$DIR/arb_v7_1_paper.py"*)
         echo "Stopping only arb V7 PID $OLD_PID"
         kill -INT "$OLD_PID" || true
         for i in $(seq 1 20); do
           if ! kill -0 "$OLD_PID" 2>/dev/null; then break; fi
           sleep 1
         done
         if kill -0 "$OLD_PID" 2>/dev/null; then
           echo "Old V7 is still running. Nothing else was stopped; refusing to start a second instance."
           exit 1
         fi
         ;;
      *)
         echo "PID file points to an unrelated process; refusing to terminate it: $CMD"
         exit 1
         ;;
    esac
  fi
fi
# Avoid silently starting if an untracked copy is running.
if pgrep -af "$DIR/arb_v7_paper.py" | grep -v -e 'pgrep -af' -e 'grep -v' >/dev/null; then
  echo "Untracked V7 old instance appears active. Review processes manually; not starting duplicate."
  exit 1
fi
if pgrep -af "$DIR/arb_v7_1_paper.py" | grep -v -e 'pgrep -af' -e 'grep -v' >/dev/null; then
  echo "Untracked V7.1 instance appears active. Review processes manually; not starting duplicate."
  exit 1
fi

echo "=== Start upgraded paper scanner: existing wallet equity retained ==="
nohup nice -n 15 "$PY" -u "$DIR/arb_v7_1_paper.py" \
  --minutes 1440 --poll 25 --coins 100 --max-book-checks 3 \
  > "$DIR/v7_1.log" 2>&1 &
echo $! > "$DIR/v7.pid"
sleep 3
tail -n 20 "$DIR/v7_1.log"
echo "=== Dashboard ==="
echo "python3 $DIR/live_dashboard_v7_1.py"
