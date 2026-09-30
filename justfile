set dotenv-load := true

# The Pulumi installer only adds ~/.pulumi/bin to ~/.bashrc, which the
# non-interactive shell running these recipes never sources.
export PATH := env_var('HOME') / ".pulumi/bin:" + env_var('PATH')

default:
    just --list

# ── Top-level ─────────────────────────────────────────────────────────────────

[group('dev')]
dev:
    bash scripts/dev.sh

[group('dev')]
db-up:
    docker compose up -d db redis

[group('dev')]
db-reset:
    docker compose down -v
    docker compose up -d db redis
    sleep 1
    cd backend && uv run python manage.py makemigrations
    cd backend && uv run python manage.py migrate
    cd backend && uv run python manage.py create_default_users
    cd backend && uv run python manage.py discover_new_symbols discover
    cd backend && uv run python manage.py sync_scheduled_tasks

[group('dev')]
install:
    just be-install
    just fe-install

# Create the single repo-root .env from the committed template.
[group('dev')]
env-init:
    cp -n .env.example .env || true

# ── Infra / Pulumi ────────────────────────────────────────────────────────────
# Container provisioning. Setup: infra/pulumi/README.md

[group('infra')]
pu-preview:
    cd infra/pulumi && PULUMI_CONFIG_PASSPHRASE_FILE=$PWD/.passphrase pulumi preview

[group('infra')]
pu-up:
    cd infra/pulumi && PULUMI_CONFIG_PASSPHRASE_FILE=$PWD/.passphrase pulumi up --yes

# Record out-of-band Proxmox changes (e.g. a disk moved to another datastore)
# in state without touching the containers
[group('infra')]
pu-refresh:
    cd infra/pulumi && PULUMI_CONFIG_PASSPHRASE_FILE=$PWD/.passphrase pulumi refresh --yes

[group('infra')]
pu-stack:
    cd infra/pulumi && PULUMI_CONFIG_PASSPHRASE_FILE=$PWD/.passphrase pulumi stack output

# There is deliberately no `pu-destroy` - both containers are protected and
# deleting production should require typing `pulumi destroy` by hand.

# ── Ansible ───────────────────────────────────────────────────────────────────

[group('infra')]
ansible-ping:
    ansible prod -i infra/ansible/inventory/hosts.yml -m ping

[group('infra')]
ansible-full:
    ansible-playbook infra/ansible/site.yml \
      -i infra/ansible/inventory/hosts.yml \
      --vault-password-file infra/ansible/.vault_password

# ── Observability (issues #2, #5) ──────────────────────────────────────────────
# Grafana + Prometheus + Loki + Tempo on stockmarket-obs (.208) plus a Grafana Alloy
# agent on every host. All of it is gated on observability_enabled in
# group_vars/prod.yml, so
# these are no-ops until that is switched on.

# Provision .208 and install/refresh Alloy on every host. Bootstrap, not an app deploy.
[group('observability')]
obs-deploy:
    # --force-handlers is load-bearing: a play that FAILS discards its pending handlers,
    # so a unit file can be rewritten on disk while the running process keeps its old
    # command line. That happened for real with the celery -E flag - the next run saw
    # the file already correct, notified nothing, and the worker stayed un-restarted.
    ansible-playbook infra/ansible/site.yml \
      -i infra/ansible/inventory/hosts.yml \
      --vault-password-file infra/ansible/.vault_password \
      --limit stockmarket-obs,stockmarket,stockmarket-db \
      --tags observability \
      --force-handlers

# Diff preview; on a FRESH host --check stops at the first dependent task (see docs).
[group('observability')]
obs-check:
    ansible-playbook infra/ansible/site.yml \
      -i infra/ansible/inventory/hosts.yml \
      --vault-password-file infra/ansible/.vault_password \
      --check --diff

[group('observability')]
obs-up:
    ssh root@192.168.2.208 'systemctl start observability-stack'

[group('observability')]
obs-down:
    ssh root@192.168.2.208 'systemctl stop observability-stack'

[group('observability')]
obs-restart:
    ssh root@192.168.2.208 'systemctl restart observability-stack'

# Tail all four server containers.
[group('observability')]
obs-logs:
    ssh root@192.168.2.208 'cd /opt/observability && docker compose logs -f --tail=100'

# Is the Alloy agent alive on every host? First question when a dashboard is empty.
[group('observability')]
obs-agents:
    ansible prod -i infra/ansible/inventory/hosts.yml -m shell \
      -a 'systemctl is-active alloy || true'

# End-to-end trace check: push one OTLP span into Alloy's LOOPBACK receiver on the app
# host, then read it back through Grafana's Tempo datasource. Proves the whole phase-2
# path at once - receiver, host attribute, batch, export, Tempo ingest, Grafana proxy.
# Every hop here fails SILENTLY in production: a wrong exporter port just queues and
# drops, and nothing logs it on either box.
[group('observability')]
obs-trace-test:
    #!/usr/bin/env bash
    set -euo pipefail
    TRACE=$(ssh root@192.168.2.200 'openssl rand -hex 16')
    SPAN=$(ssh root@192.168.2.200 'openssl rand -hex 8')
    NOW=$(date +%s); START=$((NOW * 1000000000)); END=$((START + 250000000))
    echo "trace_id=$TRACE"
    ssh root@192.168.2.200 "curl -sf -X POST http://127.0.0.1:4318/v1/traces \
      -H 'Content-Type: application/json' -d '{\"resourceSpans\":[{\"resource\":{\"attributes\":[{\"key\":\"service.name\",\"value\":{\"stringValue\":\"obs-trace-test\"}}]},\"scopeSpans\":[{\"spans\":[{\"traceId\":\"$TRACE\",\"spanId\":\"$SPAN\",\"name\":\"obs-trace-test\",\"kind\":1,\"startTimeUnixNano\":\"$START\",\"endTimeUnixNano\":\"$END\",\"status\":{}}]}]}]}' > /dev/null"
    echo "span accepted by alloy; waiting for the 2s batch flush"
    sleep 8
    ssh root@192.168.2.208 "cd /opt/observability && PW=\$(grep -m1 '^GF_SECURITY_ADMIN_PASSWORD=' .env | cut -d= -f2-) && \
      curl -sf -u \"admin:\$PW\" 'http://localhost:3000/api/datasources/proxy/uid/tempo/api/traces/$TRACE' \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); b=d.get(\"batches\") or d.get(\"resourceSpans\"); s=b[0][\"scopeSpans\"][0][\"spans\"][0]; a={x[\"key\"]:list(x[\"value\"].values())[0] for x in s.get(\"attributes\",[])}; print(\"OK: span\", s[\"name\"], \"attrs\", a)'"

# Ask the live Prometheus for every dashboard panel's query. A metric-name typo renders
# as "No data", which is indistinguishable from "idle" by eye - this is the only check
# that tells them apart. Needs the LAN stack, so it is not a CI check.
[group('observability')]
obs-verify *ARGS:
    python3 infra/observability/verify_dashboards.py {{ARGS}}

[group('infra')]
ansible-db:
    ansible-playbook infra/ansible/db.yml \
      -i infra/ansible/inventory/hosts.yml \
      --vault-password-file infra/ansible/.vault_password

[group('infra')]
deploy-log:
    ssh app@stockmarket "tail -f /home/app/deploy.log"

[group('infra')]
prod-discover:
    ssh root@stockmarket "cd /home/app/stock_market/backend && /home/app/.local/bin/uv run python manage.py discover_new_symbols"

[group('infra')]
prod-superuser:
    ssh root@stockmarket "cd /home/app/stock_market/backend && /home/app/.local/bin/uv run python manage.py create_default_users"

# ── Backend ───────────────────────────────────────────────────────────────────

[group('backend')]
be-install:
    cd backend && uv sync

[group('backend')]
be-dev:
    cd backend && uv run python manage.py migrate && uv run python manage.py runserver 0.0.0.0:8004

[group('backend')]
be-test:
    cd backend && uv run pytest

[group('backend')]
be-test-cov:
    cd backend && uv run pytest --cov=apps --cov-report=term-missing

[group('backend')]
be-lint:
    cd backend && uv run ruff check .

[group('backend')]
be-fmt:
    cd backend && uv run ruff format .

[group('backend')]
be-makemigrations:
    cd backend && uv run python manage.py makemigrations

[group('backend')]
be-migrate:
    cd backend && uv run python manage.py migrate

[group('backend')]
be-sync-tasks:
    cd backend && uv run python manage.py sync_scheduled_tasks

[group('backend')]
be-discover:
    cd backend && uv run python manage.py discover_new_symbols discover

[group('backend')]
be-shell:
    cd backend && uv run python manage.py shell

[group('backend')]
be-superuser:
    cd backend && uv run python manage.py create_default_users

# Install the Chromium the browser agent (/browse) drives. One-off, ~500 MB.
# Via uvx, not uv run: playwright is not a project dependency - browser-use only shells
# out to it to fetch the binary, then talks to Chromium over CDP.
# Two steps, not `install --with-deps`: the deps half is apt and needs root, and when
# it cannot elevate it is skipped QUIETLY - you get the binary with no shared libraries
# and a "libnspr4.so: cannot open shared object file" only at first run.
# playwright resolves the package list as YOU (uv puts uvx in ~/.local/bin, which is not
# on sudo's secure_path, so `sudo uvx` is "command not found"); only apt-get is elevated.
# That also keeps root from writing root-owned files into your ~/.cache/uv.
[group('backend')]
be-browser-setup:
    uvx playwright install-deps --dry-run chromium | tail -n +2 | xargs -r sudo apt-get install -y
    uvx playwright install chromium

# Live browser-agent smoke test - launches a real browser and reaches the internet.
[group('backend')]
be-browse query:
    cd backend && uv run python manage.py browse "{{ query }}"

[group('backend')]
be-celery:
    cd backend && uv run celery -A core worker -Q default -c 4 --max-tasks-per-child=200 -l INFO

[group('backend')]
be-celery-heavy:
    cd backend && uv run celery -A core worker -Q heavy -c 2 --max-tasks-per-child=50 -l INFO

[group('backend')]
be-beat:
    cd backend && uv run celery -A core beat -l INFO --scheduler django_celery_beat.schedulers:DatabaseScheduler

[group('backend')]
be-flower:
    cd backend && uv run celery -A core flower --port=5555

# ── Frontend ──────────────────────────────────────────────────────────────────

[group('frontend')]
fe-install:
    cd frontend && npm install

[group('frontend')]
fe-dev:
    cd frontend && npm run dev

[group('frontend')]
fe-test:
    cd frontend && npm run test

[group('frontend')]
fe-build:
    cd frontend && npm run build

[group('frontend')]
fe-lint:
    cd frontend && npm run lint


# ── Load testing (issue #12) ──────────────────────────────────────────────────
# k6 against the real API. Read-only traffic only; see docs/project_docs/load-testing.md.

k6_version := "v2.3.0"

# No anonymous usage stats from our runs - the same policy as browser-use's telemetry.
export K6_NO_USAGE_REPORT := "true"

# The static k6 binary into ~/.local/bin. NOT Docker: the daemon on the dev box runs on
# another host and cannot see repo paths, so `docker run -v` mounts an empty directory
# where the script should be. No sudo - nothing here needs root.
[group('loadtest')]
lt-install:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "$HOME/.local/bin"
    if [ -x "$HOME/.local/bin/k6" ] && "$HOME/.local/bin/k6" version | grep -q "{{ k6_version }}"; then
      echo "k6 {{ k6_version }} already installed"; exit 0
    fi
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    name="k6-{{ k6_version }}-linux-amd64"
    curl -fsSL "https://github.com/grafana/k6/releases/download/{{ k6_version }}/$name.tar.gz" | tar -xz -C "$tmp"
    install -m 0755 "$tmp/$name/k6" "$HOME/.local/bin/k6"
    "$HOME/.local/bin/k6" version

# Create/refresh the dedicated non-staff load-test user (LOADTEST_EMAIL/LOADTEST_PASSWORD).
[group('loadtest')]
lt-user:
    cd backend && uv run python manage.py ensure_loadtest_user

# Parse every script and evaluate its options without sending a single request.
# `-e`, not an exported variable: unlike `k6 run`, `k6 inspect` does NOT pass the system
# environment through, so an exported LOADTEST_PROFILE would be silently ignored and
# every iteration of this loop would inspect the default profile.
[group('loadtest')]
lt-inspect:
    #!/usr/bin/env bash
    set -euo pipefail
    for profile in smoke load stress spike soak; do
      for script in loadtest/k6/scenarios/*.js; do
        k6 inspect -e LOADTEST_PROFILE=$profile "$script" > /dev/null
        echo "ok  $profile  $script"
      done
    done

# 1 VU for 30 s against local `just dev`. Proves the scripts work, measures nothing.
[group('loadtest')]
lt-smoke:
    just lt smoke local

# PROFILE: smoke | load | stress | spike | soak.  TARGET: local | prod.
# Results go to Prometheus on .208 (dashboard `Load Testing`, uid sm-loadtest) under a
# per-run `testid`, plus a JSON summary in loadtest/results/. Set LOADTEST_OUTPUT=none
# to skip the remote write (e.g. off the LAN).
# TARGET=prod additionally needs LOADTEST_ALLOW_PROD=1 in the environment; the script
# itself refuses too, so bypassing this recipe does not bypass the guard.
[group('loadtest')]
lt PROFILE="smoke" TARGET="local" *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "{{ TARGET }}" = "prod" ] && [ "${LOADTEST_ALLOW_PROD:-}" != "1" ]; then
      echo "refusing to load-test prod: set LOADTEST_ALLOW_PROD=1 for this run" >&2; exit 2
    fi
    export LOADTEST_PROFILE="{{ PROFILE }}" LOADTEST_TARGET="{{ TARGET }}"
    export LOADTEST_TESTID="${LOADTEST_TESTID:-{{ PROFILE }}-{{ TARGET }}-$(date -u +%Y%m%dT%H%M%SZ)}"
    mkdir -p loadtest/results
    out=()
    if [ "${LOADTEST_OUTPUT:-prometheus}" = "prometheus" ]; then
      export K6_PROMETHEUS_RW_SERVER_URL="${K6_PROMETHEUS_RW_SERVER_URL:-http://192.168.2.208:9090/api/v1/write}"
      export K6_PROMETHEUS_RW_TREND_STATS="p(95),p(99),avg,max"
      out=(-o experimental-prometheus-rw)
    fi
    echo "testid=$LOADTEST_TESTID"
    k6 run "${out[@]}" {{ ARGS }} loadtest/k6/scenarios/browse.js

[group('CI/CD')]
actions:
    gh run list --limit 8