---
name: env-config
description: "Single repo-root .env after issue #4 — who reads it, the systemd format constraint that governs it, and the failure modes that are silent"
metadata:
  type: project
---

Configuration is ONE file: `.env` at the repo root, template `.env.example` (committed).
Consolidated by [issue #4](https://github.com/bthek1/Market_Analyzer/issues/4) on 2026-09-21
from six scattered locations. Applied to prod the same day.

**Readers:** Django (`core/env.py` -> `settings.ENV_FILE`), Vite (`envDir: '..'`), docker
compose (`${VAR:-default}`, auto-loaded), `scripts/dev.sh`, `.vscode/launch.json` +
`settings.json` (`envFile`), and on prod the three systemd units' `EnvironmentFile`,
rendered from the Ansible vault by `roles/deploy/templates/env.j2`.

**Why:** the same value lived in several files and drifted - the repo documented the DB
port as 5434 while compose published 5435, and `deploy.sh` hardcoded
`VITE_API_BASE_URL=http://192.0.2.200` next to an Ansible template that never set it.

**How to apply:**

- **There is no fallback.** `backend/.env` and `frontend/.env` are deleted, including on
  prod. A missing root file means code defaults, not a second lookup. `frontend/.env.test`
  is the one deliberate exception (vitest must not depend on local config).
- **systemd is the strictest consumer and sets the format**: flat `KEY=value`, no `export`,
  no `${VAR}`, no `$(cmd)`, no multi-line values. This is why the prod `SECRET_KEY` is
  generated **alphanumeric-only** - Django's own `get_random_secret_key` alphabet contains
  `#` (truncates the value at a comment) and `$`.
- **The `VITE_` prefix is a security boundary, not a convention.** It is the only thing
  keeping `SECRET_KEY` and `ANTHROPIC_API_KEY` out of the browser bundle, so `envPrefix`
  must never be set in `vite.config.ts`. Verified by building with a canary: a non-prefixed
  value is absent from `dist/`. Note an *unreferenced* `VITE_*` key is also absent - Vite
  inlines only keys the code reads - so a bundle grep only proves anything with a key the
  app actually uses.
- **Changing the prod env needs a restart, not just an `ansible-playbook` run.** systemd
  reads `EnvironmentFile` at process start only; the `services` role reloads systemd but
  does not restart the units, so a re-render sits dormant until the next deploy or reboot.
- **The guard is `backend/core/tests/test_env_contract.py`** (17 tests) plus
  `frontend/src/test/env-contract.test.ts` (5). They cover every consumer, not just the
  file: undocumented required keys, dead keys, systemd-unsafe lines, hardcoded compose
  credentials/ports, a compose default drifting from `.env.example`, `DATABASE_URL`
  disagreeing with `POSTGRES_PORT`, `env.j2` missing a key prod cannot default, a systemd
  unit pointing elsewhere, `deploy.sh` re-hardcoding the URL, and any `VITE_*` key the app
  reads but the example does not declare. Each was mutation-tested - break the thing, watch
  the test fail.
- **A checkout predating the migration fails at boot**, not silently: no fallback is left,
  so Django raises `ImproperlyConfigured: SECRET_KEY`. The fix is `just env-init` plus
  re-entering the secrets. The one-shot `env-migrate` helper that folded the old files in
  was deleted on 2026-09-22 once every machine was migrated (recoverable from git history
  at `scripts/env_migrate.sh` if another stale checkout turns up).

Related: [[project-state]], [[observability]] (the `LOG_*` / `REQUEST_ID_HEADER` keys).
