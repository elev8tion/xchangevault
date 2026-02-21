#!/usr/bin/env bash
# Sign a macOS .app bundle with your Apple Developer ID certificate.
# Usage:
#   ./sign-app.sh "XchangeVault.app" "Developer ID Application: Your Name (TEAMID)"

set -euo pipefail

APP_PATH="${1:-XchangeVault.app}"
IDENTITY="${2:-}"

if [ -z "$IDENTITY" ]; then
  echo "❌ Missing identity."
  echo "Usage: $0 <App.app> \"Developer ID Application: Your Name (TEAMID)\""
  exit 1
fi

if [ ! -d "$APP_PATH" ]; then
  echo "❌ App not found: $APP_PATH"
  exit 1
fi

echo "🔏 Signing: $APP_PATH"
echo "👤 Identity: $IDENTITY"

# Remove quarantine to avoid gatekeeper blocking during sign/verify
if xattr -p com.apple.quarantine "$APP_PATH" >/dev/null 2>&1; then
  xattr -dr com.apple.quarantine "$APP_PATH" || true
fi

# Sign with hardened runtime for best compatibility
codesign --deep --force --options runtime --sign "$IDENTITY" "$APP_PATH"

echo "✅ codesign done. Verifying..."
codesign --verify --deep --strict "$APP_PATH"
echo "✅ codesign verify ok"

echo "🛡  Gatekeeper assessment (spctl):"
spctl -a -v "$APP_PATH" || true

echo "✨ Signed successfully"
