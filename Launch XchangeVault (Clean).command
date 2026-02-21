#!/usr/bin/env bash
# Convenience launcher to start with a clean state
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
CLEAN_START=1 open "$DIR/XchangeVault.app"
