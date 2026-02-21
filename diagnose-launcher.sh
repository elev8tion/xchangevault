#!/usr/bin/env bash
set -x
exec 2>&1

APP_NAME="XchangeVault"
PYTHON_SCRIPT="server.py"
PORT=3000

echo "═══════════════════════════════════════"
echo "$APP_NAME LAUNCHER DIAGNOSTIC"
echo "═══════════════════════════════════════"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Project dir: $SCRIPT_DIR"

echo "\n1. Checking required files..."
for f in "$PYTHON_SCRIPT" "frontend/index.html" "requirements.txt"; do
  if [ -f "$SCRIPT_DIR/$f" ]; then echo "  ✓ $f"; else echo "  ✗ $f NOT FOUND"; fi
done

echo "\n2. Python..."
which python3 && python3 --version
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"
if [ -f "$VENV_PYTHON" ]; then
  echo "  ✓ venv python: $VENV_PYTHON"
  "$VENV_PYTHON" -c "import openai; print('  ✓ openai')" 2>/dev/null || echo "  ✗ openai not installed"
  "$VENV_PYTHON" -c "import tiktoken; print('  ✓ tiktoken')" 2>/dev/null || echo "  ⚠ tiktoken not installed (optional)"
else
  echo "  ✗ No venv — run setup.sh"
fi

echo "\n3. Port availability..."
for p in {3000..3009}; do
  lsof -i :"$p" >/dev/null 2>&1 && echo "  :$p IN USE" || echo "  :$p free"
done

echo "\n4. App bundle..."
ls -la "$SCRIPT_DIR/XchangeVault.app/Contents/MacOS" || true
ls -la "$SCRIPT_DIR/XchangeVault.app/Contents/Resources" || true
ls -la "$SCRIPT_DIR/XchangeVault.app/Contents/Info.plist" || true

echo "\nDone."
