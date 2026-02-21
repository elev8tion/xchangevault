#!/usr/bin/env bash
# Create a macOS launcher bundle for any local Python web app.
# Usage:
#   bash create-mac-launcher.sh "AppName" "com.company.app" "server.py" [icon.icns]

set -euo pipefail

APP_NAME="${1:-}"
BUNDLE_ID="${2:-}"
PYTHON_SCRIPT="${3:-server.py}"
ICON_PATH="${4:-}"

if [ -z "$APP_NAME" ] || [ -z "$BUNDLE_ID" ]; then
  echo "Usage: $0 \"AppName\" \"com.company.app\" \"server.py\" [icon.icns]"
  exit 1
fi

DISPLAY_NAME="$APP_NAME"
APP_DIR="${APP_NAME}.app"
APP_SLUG=$(echo "$APP_NAME" | tr '[:upper:] ' '[:lower:]-')
PID_BASENAME=${APP_SLUG//-/_}

echo "🚀 Creating Mac launcher for: $APP_NAME"

# 1) Bundle scaffold
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"
printf 'APPL????' > "$APP_DIR/Contents/PkgInfo"

# 2) Info.plist
cat > "$APP_DIR/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>en</string>
    <key>CFBundleExecutable</key>
    <string>$APP_NAME</string>
    <key>CFBundleIdentifier</key>
    <string>$BUNDLE_ID</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>$DISPLAY_NAME</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSApplicationCategoryType</key>
    <string>public.app-category.developer-tools</string>
</dict>
</plist>
EOF

# 3) Main launcher script (no extension)
cat > "$APP_DIR/Contents/MacOS/$APP_NAME" <<'LAUNCH_EOF'
#!/usr/bin/env bash
set -euo pipefail

APP_DISPLAY_NAME="__DISPLAY_NAME__"
PYTHON_SCRIPT="__PY_SCRIPT__"
PORT_START=3000
PORT_END=3009
PID_DIR="$HOME/.__PID_BASE__"
LOG_KEEP_DAYS=7
INACTIVITY_TIMEOUT=600

BUNDLE_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PROJECT_DIR="$(dirname "$BUNDLE_DIR")"

REQUIRED_FILES=("$PYTHON_SCRIPT")
if [ -f "$PROJECT_DIR/frontend/index.html" ]; then
  REQUIRED_FILES+=("frontend/index.html")
fi

for f in "${REQUIRED_FILES[@]}"; do
  if [ ! -f "$PROJECT_DIR/$f" ]; then
    osascript -e "display dialog \"Error: Required file not found:\n\n$PROJECT_DIR/$f\n\nPlease keep ${APP_DISPLAY_NAME}.app in its original project folder.\" buttons {\"OK\"} default button 1 with icon stop with title \"${APP_DISPLAY_NAME}\""
    exit 1
  fi
done

cd "$PROJECT_DIR"

PY="$PROJECT_DIR/venv/bin/python3"
if [ ! -x "$PY" ]; then
  for c in "/opt/homebrew/bin/python3" "/usr/local/bin/python3" "$(command -v python3 2>/dev/null || true)"; do
    if [ -x "$c" ]; then PY="$c"; break; fi
  done
fi
if [ ! -x "$PY" ]; then
  osascript -e "display dialog \"Python 3 not found.\nRun setup.sh first.\" buttons {\"OK\"} default button 1 with icon stop with title \"${APP_DISPLAY_NAME}\""; exit 1
fi

EXTRA_FLAGS=""
if [ "${CLEAN_START:-}" = "1" ]; then EXTRA_FLAGS="--clean"; fi

PID_FILE="$PID_DIR/server.pid"
mkdir -p "$PID_DIR"
if [ -f "$PID_FILE" ]; then
  OLD=$(cat "$PID_FILE"); kill "$OLD" 2>/dev/null || true; sleep 1; kill -9 "$OLD" 2>/dev/null || true; rm -f "$PID_FILE"
fi
pkill -f "python.*$PYTHON_SCRIPT" 2>/dev/null || true

PORT=$PORT_START
while lsof -i :"$PORT" >/dev/null 2>&1 && [ "$PORT" -lt "$PORT_END" ]; do PORT=$((PORT+1)); done
if lsof -i :"$PORT" >/dev/null 2>&1; then osascript -e "display dialog \"No available port found.\" buttons {\"OK\"} default button 1 with icon stop with title \"${APP_DISPLAY_NAME}\""; exit 1; fi

LOG_DIR="$PID_DIR/logs"; mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/__PID_BASE__-$(date +%Y%m%d-%H%M%S).log"
find "$LOG_DIR" -name "*.log" -mtime +"$LOG_KEEP_DAYS" -delete 2>/dev/null || true

INACTIVITY_TIMEOUT="$INACTIVITY_TIMEOUT" "$PY" -u "$PYTHON_SCRIPT" --port "$PORT" > "$LOG_FILE" 2>&1 &
SERVER_PID=$!; echo "$SERVER_PID" > "$PID_FILE"
sleep 2
if ! kill -0 "$SERVER_PID" 2>/dev/null; then
  TAIL=$(tail -20 "$LOG_FILE" 2>/dev/null || echo "(no log)")
  osascript -e "display dialog \"Server failed to start.\nLog: $LOG_FILE\n\nLast output:\n${TAIL:0:300}\" buttons {\"OK\"} default button 1 with icon stop with title \"${APP_DISPLAY_NAME}\""; exit 1
fi

osascript -e "open location \"http://localhost:$PORT\""
osascript -e "display notification \"Running on port $PORT\" with title \"${APP_DISPLAY_NAME}\""
exit 0
LAUNCH_EOF

# Fill placeholders
sed -i '' "s|__DISPLAY_NAME__|$DISPLAY_NAME|g" "$APP_DIR/Contents/MacOS/$APP_NAME"
sed -i '' "s|__PY_SCRIPT__|$PYTHON_SCRIPT|g" "$APP_DIR/Contents/MacOS/$APP_NAME"
sed -i '' "s|__PID_BASE__|$PID_BASENAME|g" "$APP_DIR/Contents/MacOS/$APP_NAME"
chmod +x "$APP_DIR/Contents/MacOS/$APP_NAME"

# 4) Optional icon
if [ -n "$ICON_PATH" ] && [ -f "$ICON_PATH" ]; then
  cp "$ICON_PATH" "$APP_DIR/Contents/Resources/AppIcon.icns"
fi

# 5) Quick-launch .command
cat > "Launch $APP_NAME (Clean).command" <<EOF
#!/usr/bin/env bash
set -e
DIR="
$(cd "$(dirname "$0")" && pwd)"
CLEAN_START=1 open "\$DIR/$APP_DIR"
EOF
chmod +x "Launch $APP_NAME (Clean).command"

# 6) Kill script
cat > "kill_${APP_SLUG}.sh" <<EOF
#!/usr/bin/env bash
APP_NAME="$APP_SLUG"
PYTHON_SCRIPT="$PYTHON_SCRIPT"
PID_FILE="\$HOME/.${PID_BASENAME}/server.pid"
echo "🧹 Stopping $APP_NAME..."
if [ -f "\$PID_FILE" ]; then PID=\$(cat "\$PID_FILE"); kill "\$PID" 2>/dev/null || true; sleep 1; kill -9 "\$PID" 2>/dev/null || true; rm -f "\$PID_FILE"; fi
PIDS=\$(pgrep -f "python.*${PYTHON_SCRIPT}" 2>/dev/null || true)
if [ -n "\$PIDS" ]; then echo "Killing: \$PIDS"; echo "\$PIDS" | xargs kill 2>/dev/null || true; sleep 1; echo "\$PIDS" | xargs kill -9 2>/dev/null || true; fi
echo "Done"
EOF
chmod +x "kill_${APP_SLUG}.sh"

echo ""
echo "✅ Created $APP_DIR"
echo "ℹ️  If blocked by Gatekeeper: xattr -cr \"$APP_DIR\""
echo "✨ Done"

