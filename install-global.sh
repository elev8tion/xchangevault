#!/usr/bin/env bash
# Install Code Extractor as a global terminal command.

set -e

APP_NAME="xchangevault"
DISPLAY_NAME="XchangeVault"
PYTHON_SCRIPT="server.py"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_DIR"

echo "🚀 Installing $DISPLAY_NAME globally..."

cat > "$INSTALL_DIR/$APP_NAME" << 'LAUNCHER_EOF'
#!/usr/bin/env bash
APP_ROOT="__APP_ROOT__"
PYTHON_SCRIPT="$APP_ROOT/__PYTHON_SCRIPT__"

PROJECT_PATH="${1:-.}"
if [ "$PROJECT_PATH" = "." ]; then
  PROJECT_PATH="$(pwd)"
else
  PROJECT_PATH="${PROJECT_PATH/#~/$HOME}"
  PROJECT_PATH="$(cd "$PROJECT_PATH" 2>/dev/null && pwd)"
fi

if [ ! -d "$PROJECT_PATH" ]; then
  echo "❌ Not a directory: $PROJECT_PATH"; exit 1
fi

PY="$APP_ROOT/venv/bin/python3"
if [ ! -x "$PY" ]; then PY="$(command -v python3 2>/dev/null || echo '')"; fi
if [ -z "$PY" ]; then echo "❌ Python 3 not found. Run setup.sh first."; exit 1; fi

echo "🚀 XchangeVault"
echo "📂 Project: $PROJECT_PATH"; echo

"$PY" "$PYTHON_SCRIPT" --port 5055
LAUNCHER_EOF

# Replace placeholders
sed -i '' "s|__APP_ROOT__|$SCRIPT_DIR|g" "$INSTALL_DIR/$APP_NAME"
sed -i '' "s|__PYTHON_SCRIPT__|$PYTHON_SCRIPT|g" "$INSTALL_DIR/$APP_NAME"

chmod +x "$INSTALL_DIR/$APP_NAME"

echo "✅ Installed: $INSTALL_DIR/$APP_NAME"
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
  echo "⚠️  Add to PATH: export PATH=\"$HOME/.local/bin:$PATH\""
fi
