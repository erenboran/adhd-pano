#!/usr/bin/env bash
# ADHD panosu — Linux/macOS baslatici
# Kullanim: ./start_adhd.sh   (Ctrl+C ile durur). Log: data/pano.log
set -euo pipefail
cd "$(dirname "$0")"

if [ -x "./.venv/bin/python" ]; then
  PY="./.venv/bin/python"
else
  PY="$(command -v python3 || command -v python || true)"
fi
if [ -z "${PY:-}" ]; then
  echo "[HATA] python3/python bulunamadi." >&2
  exit 1
fi

echo "ADHD panosu basliyor: http://127.0.0.1:5077  ($PY)"
exec "$PY" ./app.py "$@"
