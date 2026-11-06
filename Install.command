#!/bin/bash
set -e
cd "$(dirname "$0")"
export PATH="/usr/local/bin:/Library/Frameworks/Python.framework/Versions/Current/bin:$PATH"
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3.10 or newer is required. Install it from python.org, then run this installer again."
    exit 1
fi
if [ -f package-manifest.json ]; then
    python3 mac_bootstrap.py
else
    python3 scripts/prepare_downloads.py
fi
