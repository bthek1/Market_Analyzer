#!/usr/bin/env bash
set -euo pipefail
LOG=/home/app/deploy.log

exec >> "$LOG" 2>&1
echo "=== Deploy triggered at $(date) ==="

cd /home/app/stock_market

# Discard any local modifications so git pull never aborts
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "Local modifications detected — restoring tracked files to HEAD"
    git checkout -- .
fi

git fetch origin --tags --force
git reset --hard origin/main

cd /home/app/stock_market/backend
git -C /home/app/stock_market describe --tags > VERSION
/home/app/.local/bin/uv sync --no-dev
/home/app/.local/bin/uv run python manage.py migrate --noinput
/home/app/.local/bin/uv run python manage.py collectstatic --noinput

cd /home/app/stock_market/frontend
npm ci --prefer-offline
# VITE_API_BASE_URL comes from the single repo-root .env that Ansible renders from
# the vault (issue #4), not from a constant in this script. Resolved and passed
# explicitly rather than left to vite's envDir, so the build fails loudly here
# instead of shipping a bundle whose API calls go to the empty string - which looks
# like a successful deploy until the first page load.
ENV_FILE=/home/app/stock_market/.env
API_BASE_URL=$(sed -n 's/^VITE_API_BASE_URL=//p' "$ENV_FILE" | tail -1)
if [ -z "$API_BASE_URL" ]; then
    echo "FATAL: VITE_API_BASE_URL is not set in $ENV_FILE - re-run the Ansible deploy role"
    exit 1
fi
VITE_API_BASE_URL="$API_BASE_URL" npm run build

sudo systemctl restart stockmarket-api stockmarket-celery stockmarket-celery-beat

# The metrics exporter runs app code too (apps/tasks/metrics.py, collectors.py), so a
# code deploy that does not restart it leaves it serving stale collectors indefinitely.
# It only exists when observability is enabled, so a missing unit must not fail the
# deploy - hence the guard rather than adding it to the line above.
if systemctl list-unit-files stockmarket-metrics.service >/dev/null 2>&1; then
    sudo systemctl restart stockmarket-metrics || echo "WARNING: stockmarket-metrics restart failed"
fi

# Run after restart so celery beat has time to re-insert its system tasks (e.g.
# celery.backend_cleanup) before we prune anything not in SCHEDULED_TASKS.
sleep 5
cd /home/app/stock_market/backend
/home/app/.local/bin/uv run python manage.py sync_scheduled_tasks

echo "=== Deploy complete at $(date) ==="
