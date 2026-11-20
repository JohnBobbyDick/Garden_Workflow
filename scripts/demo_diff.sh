#!/usr/bin/env bash
# Diff-aware demo (§12А.1): PR with a generated AWS key → FAIL + PR comment → key removed → PASS, comment updated.
# The API must run with APP_SCAN_ROOTS including $AISW_DEMO_ROOT and APP_SSRF_ALLOW_HOSTS=127.0.0.1:$AISW_MOCK_SCM_PORT.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
[ -x "$PY" ] || PY="$ROOT/backend/.venv/Scripts/python.exe"
exec "$PY" "$ROOT/scripts/demo_diff.py" "$@"
