#!/usr/bin/env bash
# One-time setup: create venv and install dependencies.
set -e

APP_NAME="XchangeVault"
echo "🔧 $APP_NAME Setup"
echo "$(printf '─%.0s' {1..30})"

if ! command -v python3 &>/dev/null; then
  echo "❌ Python 3 not found. Install via: brew install python3"; exit 1
fi
echo "✅ Python $(python3 --version)"

VENV_DIR="$(cd "$(dirname "$0")" && pwd)/venv"
if [ ! -d "$VENV_DIR" ]; then
  echo "\n📦 Creating virtual environment..."
  python3 -m venv "$VENV_DIR"
  echo "✅ venv created at $VENV_DIR"
fi

echo "\n📦 Installing dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$(cd "$(dirname "$0")" && pwd)/requirements.txt"
echo "✅ Dependencies installed"

for f in "$(cd "$(dirname "$0")" && pwd)"/*.sh; do chmod +x "$f" 2>/dev/null || true; done
chmod +x "$(cd "$(dirname "$0")" && pwd)/XchangeVault.app/Contents/MacOS/XchangeVault" 2>/dev/null || true

echo "\n✨ Setup complete!"
echo "Run:"
echo "  python3 server.py --port 5055     # Terminal"
echo "  open XchangeVault.app            # Finder / double-click"
echo "  ./install-global.sh               # Install global CLI command"
