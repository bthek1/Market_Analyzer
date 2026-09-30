#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Single repo-root .env (issue #4). Create it with `just env-init`.
set -a
# shellcheck source=/dev/null
[ -f "$ROOT/.env" ] && source "$ROOT/.env"
set +a

docker compose -f "$ROOT/docker-compose.yml" up -d db redis

(cd "$ROOT/backend" && uv run python manage.py migrate)
(cd "$ROOT/backend" && uv run python manage.py sync_scheduled_tasks)

(cd "$ROOT/frontend" && exec npm run dev) &
FE_PID=$!

(cd "$ROOT/backend" && exec uv run celery -A core worker -l info) &
CELERY_PID=$!

(cd "$ROOT/backend" && exec uv run celery -A core beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler) &
BEAT_PID=$!

cleanup() {
    echo ""
    echo "Shutting down..."
    # Second SIGINT = celery cold shutdown (first came from Ctrl+C)
    kill -INT "$CELERY_PID" 2>/dev/null
    kill "$BEAT_PID" 2>/dev/null
    kill "$FE_PID" 2>/dev/null
    wait "$FE_PID" "$CELERY_PID" "$BEAT_PID" 2>/dev/null
    echo "Done."
}
trap cleanup EXIT

cd "$ROOT/backend" && uv run python manage.py runserver 0.0.0.0:8004
