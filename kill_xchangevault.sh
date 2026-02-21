#!/usr/bin/env bash
# Kill XchangeVault server processes

APP_NAME="xchangevault"
PYTHON_SCRIPT="server.py"
PID_FILE="$HOME/.${APP_NAME}/server.pid"

echo "🧹 Stopping $APP_NAME..."

if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    echo "  Killing PID $PID (from pid file)..."
    kill "$PID" 2>/dev/null || true
    sleep 1
    kill -9 "$PID" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
fi

PIDS=$(pgrep -f "python.*${PYTHON_SCRIPT}" 2>/dev/null || true)
if [ -n "$PIDS" ]; then
  echo "  Killing orphaned processes: $PIDS"
  echo "$PIDS" | xargs kill    2>/dev/null || true
  sleep 1
  echo "$PIDS" | xargs kill -9 2>/dev/null || true
  echo "  ✓ Done"
else
  echo "  No running processes found"
fi

echo ""
echo "Port status (3000-3009):"
for port in {3000..3009}; do
  if lsof -i :"$port" >/dev/null 2>&1; then
    echo "  :$port  IN USE"
  else
    echo "  :$port  free"
  fi
done

echo ""
echo "✨ Done"
