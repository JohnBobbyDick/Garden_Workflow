#!/bin/sh
# api: apply Alembic migrations, then serve the API. worker: run the queue worker + scheduler.
# mock: local Telegram/SMTP/Webhook + GitHub/GitLab mocks (demo without internet).
set -e
cd /app/backend
case "${1:-api}" in
  api)
    alembic upgrade head
    # forwarded headers are trusted only from FORWARDED_ALLOW_IPS (default: none besides localhost), so a client
    # cannot spoof X-Forwarded-For to dodge the per-IP login rate limit
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}"
    ;;
  worker)
    exec python -m app.engine.worker
    ;;
  mock)
    python /app/scripts/mock_scm.py &
    exec python /app/scripts/mock_services.py
    ;;
  *)
    exec "$@"
    ;;
esac
