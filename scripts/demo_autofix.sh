#!/usr/bin/env bash
# AI AutoFix demo (§12А.3): password → AutoFix (checklist + diff) → PR on mock GitHub → diff-aware re-check of the
# autofix branch (0 new) → organizer repository: .patch only.
# The API must run with APP_SCAN_ROOTS including fixtures and $AISW_DEMO_ROOT, and
# APP_SSRF_ALLOW_HOSTS=127.0.0.1:$AISW_MOCK_SCM_PORT,127.0.0.1:$AISW_DEMO_LLM_PORT.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
[ -x "$PY" ] || PY="$ROOT/backend/.venv/Scripts/python.exe"
exec "$PY" "$ROOT/scripts/demo_autofix.py" "$@"
