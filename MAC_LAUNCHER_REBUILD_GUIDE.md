# Mac Launcher — Full Rebuild Guide

> Extracted from **Codebase Cartographer** — everything needed to package any Python web-app
> as a double-clickable macOS `.app`, a `.command` file, a global CLI command, and a kill script.

---

## Table of Contents

1. [How the Full Launcher Stack Works](#how-the-full-launcher-stack-works)
2. [File Structure to Create](#file-structure-to-create)
3. [Layer 1 — The .app Bundle](#layer-1--the-app-bundle)
   - [Bundle directory scaffold](#bundle-directory-scaffold)
   - [Info.plist](#infoplist)
   - [PkgInfo](#pkginfo)
   - [The main launcher shell script](#the-main-launcher-shell-script)
   - [Custom app icon (.icns)](#custom-app-icon-icns)
4. [Layer 2 — The .command Quick-Launch File](#layer-2--the-command-quick-launch-file)
5. [Layer 3 — Global Terminal Command (carto / your-app-name)](#layer-3--global-terminal-command)
   - [install-global.sh](#install-globalsh)
6. [Layer 4 — Kill / Cleanup Script](#layer-4--kill--cleanup-script)
7. [Layer 5 — Setup / Dependency Script](#layer-5--setup--dependency-script)
8. [Layer 6 — Diagnostic Script](#layer-6--diagnostic-script)
9. [PID File Pattern — Reliable Process Management](#pid-file-pattern)
10. [Port Detection Pattern](#port-detection-pattern)
11. [osascript Notifications & Dialogs Cheat Sheet](#osascript-notifications--dialogs-cheat-sheet)
12. [macOS Permissions & Gatekeeper](#macos-permissions--gatekeeper)
13. [Auto-Shutdown in the Python Server](#auto-shutdown-in-the-python-server)
14. [Adapting Everything for Your App](#adapting-everything-for-your-app)
15. [Quick-Start: Full Build in One Script](#quick-start-full-build-in-one-script)

---

## How the Full Launcher Stack Works

```
Double-click  ──►  Cartographer.app/Contents/MacOS/YourApp  (bash script)
                        │
                        ├── kills old PID (if any)
                        ├── finds free port (3000–3009)
                        ├── starts  python server.py --port $PORT  in background
                        ├── saves PID to ~/.yourapp/server.pid
                        ├── waits 2s, checks server is alive
                        ├── opens http://localhost:$PORT in default browser
                        └── sends macOS notification "Server running on port X"

.command file  ──►  clears history / state, then opens the .app

Terminal CLI  ──►  ~/.local/bin/yourapp  (bash)  ──►  python server.py $PATH

kill.sh  ──►  reads ~/.yourapp/server.pid → kills → pkill fallback → reports ports

Python server  ──►  inactivity monitor thread  ──►  auto-exits after N minutes idle
```

---

## File Structure to Create

```
YourProject/
├── server.py                        ← your Python server
├── dashboard.html                   ← your frontend
├── requirements.txt
│
├── YourApp.app/                     ← the .app bundle (Finder sees this as an icon)
│   └── Contents/
│       ├── Info.plist
│       ├── PkgInfo
│       ├── MacOS/
│       │   └── YourApp              ← executable bash script (no extension)
│       └── Resources/
│           └── AppIcon.icns         ← optional custom icon
│
├── Launch YourApp (Clean).command   ← convenience double-click launcher
├── setup.sh                         ← install deps, create venv
├── install-global.sh                ← installs  yourapp  CLI command
├── kill_yourapp.sh                  ← kill running server
└── diagnose-launcher.sh             ← troubleshooting script
```

---

## Layer 1 — The .app Bundle

### Bundle directory scaffold

Run this once to create the skeleton (replace `YourApp` and `com.yourcompany.yourapp`):

```bash
APP_NAME="YourApp"
mkdir -p "${APP_NAME}.app/Contents/MacOS"
mkdir -p "${APP_NAME}.app/Contents/Resources"
touch    "${APP_NAME}.app/Contents/PkgInfo"
```

Then create the three files below.

---

### Info.plist

`YourApp.app/Contents/Info.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <!-- Required keys -->
    <key>CFBundleDevelopmentRegion</key>
    <string>en</string>

    <key>CFBundleExecutable</key>
    <string>YourApp</string>          <!-- MUST match the script filename in MacOS/ -->

    <key>CFBundleIdentifier</key>
    <string>com.yourcompany.yourapp</string>   <!-- reverse-DNS; unique per app -->

    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>

    <key>CFBundleName</key>
    <string>YourApp</string>

    <key>CFBundlePackageType</key>
    <string>APPL</string>

    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>

    <key>CFBundleVersion</key>
    <string>1</string>

    <!-- macOS compatibility -->
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>            <!-- High Sierra and later -->

    <!-- Retina display support -->
    <key>NSHighResolutionCapable</key>
    <true/>

    <!-- Icon (filename without extension) -->
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>

    <!-- Shown in App Store / Finder Get Info -->
    <key>LSApplicationCategoryType</key>
    <string>public.app-category.developer-tools</string>

    <key>NSHumanReadableCopyright</key>
    <string>Copyright © 2026 YourCompany. All rights reserved.</string>
</dict>
</plist>
```

**Keys you always need to change:**
| Key | What to set |
|---|---|
| `CFBundleExecutable` | Exact filename of your script in `MacOS/` |
| `CFBundleIdentifier` | Unique reverse-DNS string |
| `CFBundleName` | Display name |
| `CFBundleShortVersionString` | Semantic version |

---

### PkgInfo

`YourApp.app/Contents/PkgInfo`

This is a plain 8-byte file — no newline needed:

```
APPL????
```

Create it with:
```bash
printf 'APPL????' > YourApp.app/Contents/PkgInfo
```

---

### The main launcher shell script

`YourApp.app/Contents/MacOS/YourApp`  ← **no file extension**

This is the heart of the launcher. Customise the ALL-CAPS variables at the top.

```bash
#!/usr/bin/env bash
#
# YourApp — macOS App Bundle Launcher
# Double-click the .app to run this.
#

set -euo pipefail

# ══════════════════════════════════════════════════
# CONFIGURE THESE FOR YOUR PROJECT
# ══════════════════════════════════════════════════
APP_DISPLAY_NAME="YourApp"
PYTHON_SCRIPT="server.py"           # relative to PROJECT_DIR
REQUIRED_FILES=("server.py" "dashboard.html")  # existence check
PORT_START=3000                     # first port to try
PORT_END=3009                       # last port to try (10 attempts)
PID_DIR="$HOME/.${APP_DISPLAY_NAME,,}"  # ~/.yourapp
LOG_KEEP_DAYS=7                     # auto-clean old logs
INACTIVITY_TIMEOUT=600              # seconds (must match Python server setting)
# ══════════════════════════════════════════════════

# ── Resolve paths ────────────────────────────────
BUNDLE_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PROJECT_DIR="$(dirname "$BUNDLE_DIR")"

# ── Validate project files ───────────────────────
for f in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$PROJECT_DIR/$f" ]; then
        osascript -e "display dialog \"Error: Required file not found:\n\n$PROJECT_DIR/$f\n\nPlease keep ${APP_DISPLAY_NAME}.app in its original project folder.\" buttons {\"OK\"} default button 1 with icon stop with title \"${APP_DISPLAY_NAME}\""
        exit 1
    fi
done

cd "$PROJECT_DIR"

# ── Find Python ──────────────────────────────────
# Priority: project venv → Homebrew → system
PYTHON_BIN="$PROJECT_DIR/venv/bin/python3"

if [ ! -f "$PYTHON_BIN" ]; then
    for candidate in \
        "/opt/homebrew/bin/python3" \
        "/usr/local/bin/python3" \
        "$(command -v python3 2>/dev/null || true)"
    do
        if [ -x "$candidate" ]; then
            PYTHON_BIN="$candidate"
            break
        fi
    done
fi

if [ ! -x "$PYTHON_BIN" ]; then
    osascript -e "display dialog \"Python 3 not found.\n\nRun setup.sh to install dependencies and create a virtual environment.\" buttons {\"OK\"} default button 1 with icon stop with title \"${APP_DISPLAY_NAME}\""
    exit 1
fi

# ── Optional: clean-start flag (set env var before launching) ──
EXTRA_FLAGS=""
if [ "${CLEAN_START:-}" = "1" ]; then
    EXTRA_FLAGS="--clean"
    osascript -e "display notification \"Starting with clean state...\" with title \"${APP_DISPLAY_NAME}\""
fi

# ── Kill existing server (if any) ────────────────
PID_FILE="$PID_DIR/server.pid"
mkdir -p "$PID_DIR"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Killing old server (PID $OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
        kill -9 "$OLD_PID" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
fi

# Kill any orphaned processes (belt-and-suspenders)
pkill -f "python.*${PYTHON_SCRIPT}" 2>/dev/null || true
sleep 0.5

# ── Find available port ──────────────────────────
PORT=$PORT_START
while lsof -i :"$PORT" >/dev/null 2>&1 && [ "$PORT" -lt "$PORT_END" ]; do
    PORT=$((PORT + 1))
done

if lsof -i :"$PORT" >/dev/null 2>&1; then
    osascript -e "display dialog \"No available port found between $PORT_START and $PORT_END.\n\nClose some applications and try again.\" buttons {\"OK\"} default button 1 with icon stop with title \"${APP_DISPLAY_NAME}\""
    exit 1
fi

# ── Set up log file ──────────────────────────────
LOG_DIR="$PID_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/${APP_DISPLAY_NAME,,}-$(date +%Y%m%d-%H%M%S).log"

# Clean logs older than LOG_KEEP_DAYS days
find "$LOG_DIR" -name "*.log" -mtime +"$LOG_KEEP_DAYS" -delete 2>/dev/null || true

# ── Start server ─────────────────────────────────
osascript -e "display notification \"Starting server on port $PORT...\" with title \"${APP_DISPLAY_NAME}\""

"$PYTHON_BIN" -u "$PYTHON_SCRIPT" $EXTRA_FLAGS --port "$PORT" > "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"

# ── Wait for server to be ready ──────────────────
echo "Waiting for server (PID $SERVER_PID) on port $PORT..."
sleep 2

if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    ERROR_TAIL=$(tail -20 "$LOG_FILE" 2>/dev/null || echo "(no log output)")
    osascript -e "display dialog \"Server failed to start.\n\nLog: $LOG_FILE\n\nLast output:\n${ERROR_TAIL:0:300}\" buttons {\"OK\"} default button 1 with icon stop with title \"${APP_DISPLAY_NAME}\""
    exit 1
fi

# ── Open browser ─────────────────────────────────
sleep 1
osascript -e "open location \"http://localhost:$PORT\""

# ── Success notification ─────────────────────────
osascript -e "display notification \"Running on port $PORT\" with title \"${APP_DISPLAY_NAME}\" subtitle \"Ready!\""

exit 0
```

**Make it executable** (required — Finder won't run it otherwise):

```bash
chmod +x "YourApp.app/Contents/MacOS/YourApp"
```

**Make the whole bundle trusted by macOS** (removes Gatekeeper quarantine):

```bash
xattr -cr YourApp.app
```

---

### Custom app icon (.icns)

Place `AppIcon.icns` in `YourApp.app/Contents/Resources/`.

**How to create one from a PNG:**

```bash
# Method 1: iconutil (built into macOS — best quality)
mkdir MyIcon.iconset
sips -z 16 16     icon.png --out MyIcon.iconset/icon_16x16.png
sips -z 32 32     icon.png --out MyIcon.iconset/icon_16x16@2x.png
sips -z 32 32     icon.png --out MyIcon.iconset/icon_32x32.png
sips -z 64 64     icon.png --out MyIcon.iconset/icon_32x32@2x.png
sips -z 128 128   icon.png --out MyIcon.iconset/icon_128x128.png
sips -z 256 256   icon.png --out MyIcon.iconset/icon_128x128@2x.png
sips -z 256 256   icon.png --out MyIcon.iconset/icon_256x256.png
sips -z 512 512   icon.png --out MyIcon.iconset/icon_256x256@2x.png
sips -z 512 512   icon.png --out MyIcon.iconset/icon_512x512.png
sips -z 1024 1024 icon.png --out MyIcon.iconset/icon_512x512@2x.png
iconutil -c icns MyIcon.iconset -o AppIcon.icns
cp AppIcon.icns "YourApp.app/Contents/Resources/AppIcon.icns"

# Method 2: Quick single-size (lower quality, zero effort)
sips -s format icns icon.png --out "YourApp.app/Contents/Resources/AppIcon.icns"
```

After placing the icon, touch the app so Finder refreshes:

```bash
touch YourApp.app
```

---

## Layer 2 — The .command Quick-Launch File

A `.command` file is a plain shell script that macOS Terminal opens and executes when
double-clicked from Finder. Use it for special launch modes (e.g. "Clean Start").

`Launch YourApp (Clean).command`

```bash
#!/usr/bin/env bash
# Double-click this in Finder to wipe saved state and launch fresh.
cd "$(dirname "$0")"

# Clear any saved state file (adapt path to your app)
rm -f ~/.yourapp_history   # or whatever your app's history file is

# Open the .app
open YourApp.app
```

**Make it executable and remove quarantine:**

```bash
chmod +x "Launch YourApp (Clean).command"
xattr -d com.apple.quarantine "Launch YourApp (Clean).command" 2>/dev/null || true
```

> The first time a user double-clicks a `.command` file macOS may warn them.
> They click "Open" once and it works forever after.
> To pre-approve it for the current machine: `xattr -cr "Launch YourApp (Clean).command"`

---

## Layer 3 — Global Terminal Command

`install-global.sh`

After running this script, the user can type `yourapp` (or `yourapp ~/myproject`) from any terminal.

```bash
#!/usr/bin/env bash
# Install YourApp as a global terminal command.
# Usage after install:
#   yourapp              → analyzes current directory
#   yourapp ~/myproject  → analyzes a specific project

# ══ CONFIGURE ═══════════════════════════════════
APP_NAME="yourapp"                  # the command name (lowercase, no spaces)
DISPLAY_NAME="YourApp"
PYTHON_SCRIPT="server.py"
# ════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_DIR"

echo "🚀 Installing $DISPLAY_NAME globally..."

cat > "$INSTALL_DIR/$APP_NAME" << LAUNCHER_EOF
#!/usr/bin/env bash
# $DISPLAY_NAME global launcher
# Auto-generated by install-global.sh

APP_ROOT="${SCRIPT_DIR}"
PYTHON_SCRIPT="\${APP_ROOT}/${PYTHON_SCRIPT}"
PROJECT_PATH="\${1:-.}"

# Resolve to absolute path
if [ "\$PROJECT_PATH" = "." ]; then
    PROJECT_PATH="\$(pwd)"
else
    PROJECT_PATH="\${PROJECT_PATH/#\~/$HOME}"
    PROJECT_PATH="\$(cd "\$PROJECT_PATH" 2>/dev/null && pwd)"
fi

if [ ! -d "\$PROJECT_PATH" ]; then
    echo "❌ Not a directory: \$PROJECT_PATH"
    exit 1
fi

# Find Python (venv preferred)
PYTHON_BIN="\${APP_ROOT}/venv/bin/python3"
if [ ! -f "\$PYTHON_BIN" ]; then
    PYTHON_BIN="\$(command -v python3 2>/dev/null || echo '')"
fi
if [ -z "\$PYTHON_BIN" ]; then
    echo "❌ Python 3 not found. Run setup.sh first."
    exit 1
fi

echo "🚀 $DISPLAY_NAME"
echo "📂 Project: \$PROJECT_PATH"
echo ""

"\$PYTHON_BIN" "\$PYTHON_SCRIPT" "\$PROJECT_PATH" "\$@"
LAUNCHER_EOF

chmod +x "$INSTALL_DIR/$APP_NAME"

echo "✅ Installed: $INSTALL_DIR/$APP_NAME"
echo ""

# Check / advise PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo "⚠️  Add this to your ~/.zshrc or ~/.bashrc:"
    echo ""
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
    echo "Then: source ~/.zshrc"
else
    echo "✅ ~/.local/bin is already in your PATH"
fi

echo ""
echo "Usage:"
echo "  $APP_NAME                 # analyze current directory"
echo "  $APP_NAME ~/myproject     # analyze specific project"
echo "  $APP_NAME --help          # show server options"
```

---

## Layer 4 — Kill / Cleanup Script

`kill_yourapp.sh`

```bash
#!/usr/bin/env bash
# Kill all running YourApp server processes.
# ══ CONFIGURE ═══════════════════════════
APP_NAME="yourapp"
PYTHON_SCRIPT="server.py"
PID_FILE="$HOME/.${APP_NAME}/server.pid"
# ════════════════════════════════════════

echo "🧹 Stopping $APP_NAME..."

# 1. Kill via PID file (cleanest)
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

# 2. pkill fallback (catches orphaned processes)
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

# 3. Report port status
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
```

---

## Layer 5 — Setup / Dependency Script

`setup.sh`

```bash
#!/usr/bin/env bash
# One-time setup: create venv and install dependencies.

set -e

APP_NAME="YourApp"
echo "🔧 $APP_NAME Setup"
echo "$(printf '─%.0s' {1..30})"

# Python check
if ! command -v python3 &>/dev/null; then
    echo "❌ Python 3 not found."
    echo "   Install via: brew install python3"
    exit 1
fi
echo "✅ Python $(python3 --version)"

# Create venv in project directory
VENV_DIR="$(dirname "$0")/venv"
if [ ! -d "$VENV_DIR" ]; then
    echo ""
    echo "📦 Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo "✅ venv created at $VENV_DIR"
fi

# Install dependencies
echo ""
echo "📦 Installing dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$(dirname "$0")/requirements.txt"
echo "✅ Dependencies installed"

# Make launcher scripts executable
for f in "$(dirname "$0")"/*.sh; do
    chmod +x "$f" 2>/dev/null || true
done
chmod +x "$(dirname "$0")/YourApp.app/Contents/MacOS/YourApp" 2>/dev/null || true

echo ""
echo "✨ Setup complete!"
echo ""
echo "Run:"
echo "  python3 server.py /path/to/project    # Terminal"
echo "  open YourApp.app                      # Finder / double-click"
echo "  ./install-global.sh                   # Install global CLI command"
```

---

## Layer 6 — Diagnostic Script

`diagnose-launcher.sh`

Use this when the `.app` double-click seems to do nothing.

```bash
#!/usr/bin/env bash
# Systematically verify every launcher dependency.
set -x
exec 2>&1

APP_NAME="YourApp"
PYTHON_SCRIPT="server.py"
PORT=3000

echo "═══════════════════════════════════════"
echo "$APP_NAME LAUNCHER DIAGNOSTIC"
echo "═══════════════════════════════════════"

# Paths
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Project dir: $SCRIPT_DIR"

# 1. Required files
echo ""
echo "1. Checking required files..."
for f in "$PYTHON_SCRIPT" "dashboard.html" "requirements.txt"; do
    if [ -f "$SCRIPT_DIR/$f" ]; then
        echo "  ✓ $f"
    else
        echo "  ✗ $f NOT FOUND"
    fi
done

# 2. Python
echo ""
echo "2. Python..."
which python3 && python3 --version

VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"
if [ -f "$VENV_PYTHON" ]; then
    echo "  ✓ venv python: $VENV_PYTHON"
    "$VENV_PYTHON" -c "import openai; print('  ✓ openai', openai.__version__)" 2>/dev/null || echo "  ✗ openai not installed"
    "$VENV_PYTHON" -c "import tiktoken; print('  ✓ tiktoken')" 2>/dev/null || echo "  ⚠ tiktoken not installed (optional)"
else
    echo "  ✗ No venv — run setup.sh"
fi

# 3. Port
echo ""
echo "3. Port $PORT..."
if lsof -i :"$PORT" >/dev/null 2>&1; then
    echo "  ⚠ Port $PORT already in use"
    lsof -i :"$PORT"
else
    echo "  ✓ Port $PORT is free"
fi

# 4. Start server briefly and test
echo ""
echo "4. Test server startup..."
cd "$SCRIPT_DIR"
PYTHON_BIN="${VENV_PYTHON:-python3}"
"$PYTHON_BIN" "$PYTHON_SCRIPT" --port "$PORT" > /tmp/diag-server.log 2>&1 &
SRV_PID=$!
echo "  Server PID: $SRV_PID"
sleep 3

if kill -0 "$SRV_PID" 2>/dev/null; then
    echo "  ✓ Server is alive"
else
    echo "  ✗ Server died immediately"
    echo "  Log:"
    cat /tmp/diag-server.log
    exit 1
fi

# 5. HTTP check
echo ""
echo "5. HTTP check..."
HTTP=$(curl -s -o /tmp/diag-resp.html -w "%{http_code}" "http://localhost:$PORT/")
if [ "$HTTP" = "200" ]; then
    echo "  ✓ HTTP 200 OK"
else
    echo "  ✗ HTTP $HTTP"
    cat /tmp/diag-server.log
fi

# 6. API check
echo ""
echo "6. API endpoints..."
curl -s "http://localhost:$PORT/api/config" | python3 -m json.tool 2>/dev/null || echo "  ✗ /api/config failed"

# Cleanup
kill "$SRV_PID" 2>/dev/null || true
echo ""
echo "═══════════════════════════════════════"
echo "DIAGNOSTIC COMPLETE — see above for ✗"
echo "═══════════════════════════════════════"
```

---

## PID File Pattern

Reliable process tracking across launches — works even after crashes.

```bash
# ── Constants ────────────────────────────────────
APP_NAME="yourapp"
PID_DIR="$HOME/.$APP_NAME"
PID_FILE="$PID_DIR/server.pid"

# ── Save PID after starting ───────────────────────
mkdir -p "$PID_DIR"
your_command &
SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"

# ── Check if still running ────────────────────────
is_running() {
    [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

# ── Kill cleanly ──────────────────────────────────
stop_server() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        kill "$PID"       2>/dev/null || true   # SIGTERM first (graceful)
        sleep 1
        kill -9 "$PID"    2>/dev/null || true   # SIGKILL if still alive
        rm -f "$PID_FILE"
    fi
}
```

**In your Python server**, write the PID file too (belt-and-suspenders):

```python
import os
from pathlib import Path

def write_pid():
    pid_dir = Path.home() / '.yourapp'
    pid_dir.mkdir(exist_ok=True)
    (pid_dir / 'server.pid').write_text(str(os.getpid()))

def remove_pid():
    pid_file = Path.home() / '.yourapp' / 'server.pid'
    pid_file.unlink(missing_ok=True)

import atexit
write_pid()
atexit.register(remove_pid)
```

---

## Port Detection Pattern

```bash
# Find first free port in range PORT_START..PORT_END
PORT=$PORT_START
PORT_END=3009

while lsof -i :"$PORT" >/dev/null 2>&1; do
    PORT=$((PORT + 1))
    if [ "$PORT" -gt "$PORT_END" ]; then
        echo "No free port found between $PORT_START and $PORT_END"
        exit 1
    fi
done

echo "Using port $PORT"
```

In Python (for the server itself to pick its own port):

```python
import socket

def find_free_port(start=3000, end=3009):
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('', port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port in range {start}–{end}")
```

---

## osascript Notifications & Dialogs Cheat Sheet

These are the macOS native UI calls used throughout the launcher.

```bash
# ── Toast notification (non-blocking, disappears automatically) ──
osascript -e 'display notification "Message here" with title "YourApp" subtitle "Optional subtitle"'

# ── Modal error dialog (blocks until user clicks OK) ────────────
osascript -e 'display dialog "Something went wrong!\n\nDetails here." buttons {"OK"} default button 1 with icon stop with title "YourApp"'

# ── Question dialog (returns button name) ───────────────────────
ANSWER=$(osascript -e 'display dialog "Open in browser?" buttons {"Cancel", "Open"} default button "Open" with title "YourApp"')
# $ANSWER will be "button returned:Open" or "button returned:Cancel"

# ── Open URL in default browser ──────────────────────────────────
osascript -e 'open location "http://localhost:3000"'

# ── Open a Finder window at a path ───────────────────────────────
osascript -e 'tell application "Finder" to open POSIX file "/path/to/folder"'

# ── Show file in Finder (reveal) ────────────────────────────────
osascript -e 'tell application "Finder" to reveal POSIX file "/path/to/file.log"'
osascript -e 'tell application "Finder" to activate'
```

**Escaping multiline strings in bash:**
```bash
LOG=$(cat /tmp/server.log | tail -5)
osascript -e "display dialog \"Log output:\n${LOG}\" buttons {\"OK\"} default button 1 with title \"YourApp\""
```

---

## macOS Permissions & Gatekeeper

**Problem**: When you double-click a new `.app`, macOS may say _"can't be opened because it is from an unidentified developer"_.

**Fix** (choose one):

```bash
# Option A: Remove quarantine attribute (best for self-use)
xattr -cr YourApp.app

# Option B: Per-file
xattr -d com.apple.quarantine YourApp.app

# Option C: User can right-click → Open (bypasses Gatekeeper once)

# Option D: Sign with Apple Developer certificate (for distribution)
codesign --deep --force --sign "Developer ID Application: Your Name (XXXXXXXXXX)" YourApp.app
```

**For `.command` and `.sh` files** — same treatment:

```bash
xattr -d com.apple.quarantine "Launch YourApp (Clean).command"
chmod +x "Launch YourApp (Clean).command"
```

**If the .app silently does nothing** — macOS may have blocked the executable.
Check with:

```bash
xattr -l YourApp.app/Contents/MacOS/YourApp
# If you see com.apple.quarantine, remove it:
xattr -d com.apple.quarantine YourApp.app/Contents/MacOS/YourApp
```

**For macOS Ventura+ (13+)** — if your script calls `curl`, `python3`, or file system paths outside the project:
- No special entitlements needed for local tools that don't access the network externally
- If you add network access to `Info.plist` or Keychain, you need proper entitlements

---

## Auto-Shutdown in the Python Server

Add this to your Python server so it quits after N minutes of inactivity.
This prevents zombie processes when users forget to kill it.

```python
import time, threading, os

LAST_REQUEST_TIME = time.time()
INACTIVITY_TIMEOUT = 600   # 10 minutes
SHUTDOWN_FLAG = threading.Event()


def touch_activity():
    """Call this at the top of every HTTP handler."""
    global LAST_REQUEST_TIME
    LAST_REQUEST_TIME = time.time()


def inactivity_monitor():
    """Background thread — kills the server after timeout."""
    while not SHUTDOWN_FLAG.is_set():
        time.sleep(30)   # check every 30 seconds
        if time.time() - LAST_REQUEST_TIME > INACTIVITY_TIMEOUT:
            print(f"\nAuto-shutdown: no activity for {INACTIVITY_TIMEOUT//60} minutes")
            os._exit(0)


# Start the monitor when the server starts
monitor = threading.Thread(target=inactivity_monitor, daemon=True)
monitor.start()
```

Add `touch_activity()` to every `do_GET` and `do_POST` handler:

```python
def do_GET(self):
    touch_activity()
    # ... rest of handler ...

def do_POST(self):
    touch_activity()
    # ... rest of handler ...
```

Also expose a manual shutdown endpoint so the browser can stop the server cleanly:

```python
# POST /api/shutdown
def handle_shutdown(self):
    self._json({'success': True})
    print("Shutdown requested via API")
    SHUTDOWN_FLAG.set()
    threading.Thread(target=lambda: (time.sleep(0.5), os._exit(0))).start()
```

And wire up OS signals:

```python
import signal, sys

def shutdown_handler(sig, frame):
    print("\nShutting down...")
    server.server_close()
    sys.exit(0)

signal.signal(signal.SIGINT,  shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)
```

---

## Adapting Everything for Your App

Here is the complete list of strings to search-and-replace when reusing this guide:

| Placeholder | Replace with | Example |
|---|---|---|
| `YourApp` | Your app display name | `MapView` |
| `yourapp` | Lowercase, no spaces (used for dirs/cmds) | `mapview` |
| `YourCompany` | Your name or company | `Acme Corp` |
| `com.yourcompany.yourapp` | Unique bundle ID | `com.acme.mapview` |
| `server.py` | Your Python entry-point filename | `app.py` |
| `dashboard.html` | Your frontend filename | `index.html` |
| `3000` / `3009` | Your preferred port range | `8080` / `8089` |
| `~/.yourapp` | Your app's state directory | `~/.mapview` |
| `DEEPSEEK_API_KEY` | Your env var name(s) | `OPENAI_API_KEY` |

---

## Quick-Start: Full Build in One Script

Run this script in any project folder to scaffold all launcher files at once.
It creates the entire structure described above.

```bash
#!/usr/bin/env bash
# create-mac-launcher.sh
# Run from inside your project directory.
# Usage: bash create-mac-launcher.sh "AppName" "com.company.app" "server.py"

APP_NAME="${1:-MyApp}"
BUNDLE_ID="${2:-com.example.myapp}"
PYTHON_SCRIPT="${3:-server.py}"
APP_NAME_LOWER="${APP_NAME,,}"
VERSION="1.0.0"

echo "🚀 Creating Mac launcher for: $APP_NAME"

# ── 1. Create .app bundle structure ──────────────
mkdir -p "${APP_NAME}.app/Contents/MacOS"
mkdir -p "${APP_NAME}.app/Contents/Resources"
printf 'APPL????' > "${APP_NAME}.app/Contents/PkgInfo"

# ── 2. Info.plist ─────────────────────────────────
cat > "${APP_NAME}.app/Contents/Info.plist" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key><string>en</string>
    <key>CFBundleExecutable</key><string>${APP_NAME}</string>
    <key>CFBundleIdentifier</key><string>${BUNDLE_ID}</string>
    <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
    <key>CFBundleName</key><string>${APP_NAME}</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>${VERSION}</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>LSMinimumSystemVersion</key><string>10.13</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>LSApplicationCategoryType</key><string>public.app-category.developer-tools</string>
</dict>
</plist>
PLIST_EOF

# ── 3. Main launcher script ───────────────────────
cat > "${APP_NAME}.app/Contents/MacOS/${APP_NAME}" << LAUNCHER_EOF
#!/usr/bin/env bash
set -euo pipefail
APP_DISPLAY_NAME="${APP_NAME}"
PYTHON_SCRIPT="${PYTHON_SCRIPT}"
PID_DIR="\$HOME/.${APP_NAME_LOWER}"
PID_FILE="\$PID_DIR/server.pid"

BUNDLE_DIR="\$(cd "\$(dirname "\$0")/../.." && pwd)"
PROJECT_DIR="\$(dirname "\$BUNDLE_DIR")"
cd "\$PROJECT_DIR"

PYTHON_BIN="\$PROJECT_DIR/venv/bin/python3"
[ ! -f "\$PYTHON_BIN" ] && PYTHON_BIN="\$(command -v python3)"

mkdir -p "\$PID_DIR/logs"
[ -f "\$PID_FILE" ] && { PID=\$(cat "\$PID_FILE"); kill "\$PID" 2>/dev/null || true; sleep 1; kill -9 "\$PID" 2>/dev/null || true; rm -f "\$PID_FILE"; }
pkill -f "python.*\${PYTHON_SCRIPT}" 2>/dev/null || true; sleep 0.5

PORT=3000
while lsof -i :"\$PORT" >/dev/null 2>&1 && [ "\$PORT" -lt 3010 ]; do PORT=\$((PORT+1)); done
LOG="\$PID_DIR/logs/\${APP_NAME_LOWER}-\$(date +%Y%m%d-%H%M%S).log"

osascript -e "display notification \"Starting on port \$PORT...\" with title \"\${APP_DISPLAY_NAME}\""
"\$PYTHON_BIN" -u "\$PYTHON_SCRIPT" --port "\$PORT" > "\$LOG" 2>&1 &
echo \$! > "\$PID_FILE"; sleep 2

if ! kill -0 \$(cat "\$PID_FILE") 2>/dev/null; then
  osascript -e "display dialog \"Server failed to start.\nLog: \$LOG\" buttons {\"OK\"} default button 1 with icon stop with title \"\${APP_DISPLAY_NAME}\""
  exit 1
fi

sleep 1
osascript -e "open location \"http://localhost:\$PORT\""
osascript -e "display notification \"Ready on port \$PORT\" with title \"\${APP_DISPLAY_NAME}\""
exit 0
LAUNCHER_EOF

chmod +x "${APP_NAME}.app/Contents/MacOS/${APP_NAME}"

# ── 4. .command (clean launch) ────────────────────
cat > "Launch ${APP_NAME} (Clean).command" << CMD_EOF
#!/usr/bin/env bash
cd "\$(dirname "\$0")"
rm -f ~/".${APP_NAME_LOWER}_history"
open "${APP_NAME}.app"
CMD_EOF
chmod +x "Launch ${APP_NAME} (Clean).command"

# ── 5. kill script ────────────────────────────────
cat > "kill_${APP_NAME_LOWER}.sh" << KILL_EOF
#!/usr/bin/env bash
echo "Stopping ${APP_NAME}..."
PID_FILE="\$HOME/.${APP_NAME_LOWER}/server.pid"
[ -f "\$PID_FILE" ] && { PID=\$(cat "\$PID_FILE"); kill "\$PID" 2>/dev/null||true; sleep 1; kill -9 "\$PID" 2>/dev/null||true; rm -f "\$PID_FILE"; }
pkill -f "python.*${PYTHON_SCRIPT}" 2>/dev/null || echo "No processes found"
echo "Done"
KILL_EOF
chmod +x "kill_${APP_NAME_LOWER}.sh"

# ── 6. setup.sh ───────────────────────────────────
cat > "setup.sh" << SETUP_EOF
#!/usr/bin/env bash
set -e
echo "🔧 ${APP_NAME} Setup"
python3 -m venv venv
venv/bin/pip install --upgrade pip -q
venv/bin/pip install -r requirements.txt
chmod +x "${APP_NAME}.app/Contents/MacOS/${APP_NAME}"
xattr -cr "${APP_NAME}.app" 2>/dev/null || true
echo "✅ Setup complete — double-click ${APP_NAME}.app to launch"
SETUP_EOF
chmod +x setup.sh

# ── 7. Remove quarantine ──────────────────────────
xattr -cr "${APP_NAME}.app" 2>/dev/null || true

echo ""
echo "✅ Created:"
echo "   ${APP_NAME}.app"
echo "   Launch ${APP_NAME} (Clean).command"
echo "   kill_${APP_NAME_LOWER}.sh"
echo "   setup.sh"
echo ""
echo "Next steps:"
echo "  1. Add requirements.txt if not already present"
echo "  2. Run: bash setup.sh"
echo "  3. Double-click: ${APP_NAME}.app"
```

---

*End of Mac Launcher Rebuild Guide — generated from Codebase Cartographer on 2026-02-21*
