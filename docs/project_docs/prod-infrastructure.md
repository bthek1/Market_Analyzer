# Production Infrastructure — Pulumi + Ansible

How the Market Analyzer runs in production, from bare Proxmox host to a
live, self-deploying app. Two layers:

1. **Pulumi** — provisions the Proxmox LXC containers (the machines).
2. **Ansible** — configures those machines once (packages, DB, services, webhook).

App code updates after that are **not** Pulumi or Ansible — they happen via
CI/CD → a webhook → `deploy.sh` (see [CI/CD Deploy Flow](#cicd-deploy-flow)).

```
Pulumi     ─create→  empty LXC containers
Ansible    ─configure→  installed + running services   (run once)
CI/CD      ─deploy→  new app code                       (every push to main)
```

---

## Topology

| Host | VMID / IP | Role | Provisioned by |
|---|---|---|---|
| Proxmox node `bthek1` | `192.0.2.70:8006` | Hypervisor | (manual / pre-existing) |
| `stockmarket` | **200** / `192.0.2.200` | App: Django API, Celery, Nginx, Redis, webhook | Pulumi + Ansible |
| `stockmarket-db` | **201** / `192.0.2.201` | PostgreSQL 16 + pgvector | Pulumi + Ansible |
| Ollama host | `192.0.2.202:11434` | Local LLM + embeddings (external) | (managed separately) |
| `stockmarket-obs` | **208** / `192.0.2.208` | Grafana + Prometheus + Loki | Pulumi + Ansible |
| Mail catcher | `192.0.2.207:1025` | SMTP sink for Grafana alerts (external) | (managed separately) |

All containers are **unprivileged Ubuntu 24.04 LXC with nesting enabled**, on
bridge `vmbr0`, static IPs on the `192.0.2.0/24` LAN, gateway `192.0.2.1`,
DNS `8.8.8.8` / `1.1.1.1`.

> Note: earlier docs described a single container (VMID 200) with a co-located
> DB. The DB is now its own container (VMID 201). Ollama runs on a third host
> (`.202`) that this stack only consumes — it is not managed here.

> **Observability** (`.208`) is provisioned by the same Pulumi program and Ansible
> inventory, but is gated behind `observability_enabled` in `group_vars/prod.yml`
> (default `false`). See [observability.md](observability.md) for the full design —
> including why collection **pushes** to the server rather than being scraped.

---

## Layer 1 — Pulumi (container provisioning)

Location: `infra/pulumi/`. A **Python** program (deps managed by `uv`) using
`pulumi-proxmoxve`, which bridges the same `bpg/proxmox` provider the previous
Terraform program used. State lives in a **local file backend**
(`pulumi login file://infra/pulumi/state`) — the direct equivalent of the old
`terraform.tfstate`.

> Migrated from Terraform in Aug 2026. The containers were **imported**, never
> recreated.

```
infra/pulumi/
  __main__.py            # the two containers + the four stack outputs
  containers.py          # shared ContainerSpec + make_container helper
  Pulumi.yaml            # project (runtime python, toolchain uv)
  Pulumi.prod.yaml       # stack config; secrets ENCRYPTED, safe to commit
  pyproject.toml         # pulumi, pulumi-proxmoxve
  state/                 # local backend state — GITIGNORED
  .passphrase            # decrypts the config secrets — GITIGNORED
  README.md              # setup + day-to-day commands
```

### Container specs (from `containers.py` + `__main__.py`)

| Resource | VMID | Cores | RAM | Swap | Disk | Startup order |
|---|---|---|---|---|---|---|
| `stockmarket` (app) | 200 | 2 | 4096 MB | 2048 MB | 40 GB | 3 |
| `stockmarketDb` | 201 | 2 | 2048 MB | 512 MB | 20 GB | 2 |

Both use template `local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst`,
tagged `stockmarket` + `pulumi`. The DB starts before the app (order 2 vs 3).

### Storage — `nvme4tb-lvm`

Container root disks live on the **4 TB NVMe SSD** LVM-thin pool
`nvme4tb-lvm`, set by the `containerDatastore` stack config value. The
containers were migrated there off the older, smaller `local-lvm` pool — the
whole homelab (including `gh-runner` VMID 111 and the Ollama host VMID 202)
now sits on that SSD.

```
nvme4tb-lvm   lvmthin   ~3.7 TiB total    # container rootfs (200, 201, 111, 202, ...)
local-lvm     lvmthin   ~794 GiB          # legacy pool, no longer used by this stack
local         dir       ~94 GiB           # LXC templates (local:vztmpl/...)
backup-2tb    dir       ~1.8 TiB          # backups
```

Note the OS **template** still comes from the `local` dir storage — only the
root disks moved. If containers are moved between pools by hand (Proxmox
"Move Storage"), Pulumi state goes stale: change `containerDatastore` to match,
then run `just pu-refresh` to record the new datastore **without**
destroying/recreating the containers (changing `disk.datastoreId` on a normal
apply forces replacement). Both containers carry `protect=True`, so such a
replacement fails loudly instead of wiping production.

### Fields Pulumi deliberately ignores

The Proxmox API cannot read back `initialization.userAccount` (root password +
SSH keys), `operatingSystem.templateFileId`, or `features`. After the import
they read as empty, which made every preview want to **replace** — i.e. destroy —
both containers. All three are ForceNew fields that can only change by rebuilding
a container, so `containers.py` pins them via `ignore_changes`. To change any of
them, rebuild the container deliberately.

### Config

Non-secret: `node = bthek1`, `containerDatastore = nvme4tb-lvm`, `sshPublicKey`.
Secret (encrypted in `Pulumi.prod.yaml`): `proxmoxve:apiToken`,
`containerPassword`. Provider connection: `proxmoxve:endpoint =
https://192.0.2.70:8006`, `proxmoxve:insecure = true` (self-signed cert).

### Commands (via `just`)

```bash
just pu-preview    # what would change
just pu-up         # apply
just pu-refresh    # record out-of-band Proxmox changes
just pu-stack      # stack outputs (container ids + hostnames)
```

There is deliberately **no `pu-destroy`** recipe — the containers are protected
and tearing down production should require typing `pulumi destroy` by hand.

> **`pu-up` can reboot the containers.** During the migration an apply that wrote
> only already-matching values for `console` / `startOnBoot` still restarted both
> containers (~10-15 s of API + DB downtime; everything recovered unaided). A
> later tags-only apply restarted nothing. Read the field list in `pu-preview`
> and treat anything beyond tags/metadata as a brief planned outage.

After the first apply the containers are booted and reachable by SSH (root, via
the injected `sshPublicKey`), but otherwise **empty** — nothing is installed yet.
That is Ansible's job.

---

## Layer 2 — Ansible (machine bootstrap)

Location: `infra/ansible/`. Runs **once** to turn empty containers into working
service hosts. **Never used for app code deploys** — that is CI/CD's job.

```
infra/ansible/
  site.yml                 # full bootstrap: db host + app host
  db.yml                   # DB host only
  ansible.cfg
  inventory/hosts.yml      # prod hosts: stockmarket (.200), stockmarket-db (.201)
  group_vars/prod.yml      # non-secret vars (app_dir, IPs, ollama, db name/user…)
  vault/prod.yml           # Ansible Vault — encrypted secrets
  .vault_password          # gitignored
  roles/
    db/                    # PostgreSQL 16 + pgvector + DB/user/grants  (on .201)
    provision/             # OS packages, app user, Python 3.13, Node 22, uv, Redis, Nginx
    deploy/                # SSH deploy key, git clone, .env, initial dep install
    services/              # systemd units (api, celery, celery-beat, metrics) + Nginx site
    webhook/               # adnanh/webhook listener on :9000 + deploy.sh
```

### Playbook structure (`site.yml`)

```yaml
- hosts: stockmarket-db   roles: [db]                                  # .201
- hosts: stockmarket      roles: [provision, deploy, services, webhook] # .200
```

Run order matters: the DB host is configured first so the app host can connect
during its initial `migrate`.

### Inventory (`inventory/hosts.yml`)

Two hosts under group `prod`, both `ansible_user: root`, keyed by
`~/.ssh/id_ed25519`:
- `stockmarket` → `192.0.2.200`
- `stockmarket-db` → `192.0.2.201`

### Roles in detail

**`db`** (runs on `.201`):
- Installs PostgreSQL 16, `postgresql-server-dev-16`, build tools.
- Builds & installs **pgvector v0.8.0** from source (`make && make install`),
  idempotent via `creates: .../vector.so`.
- Creates DB `stockmarket` + user `stockmarket` (password from vault), grants
  ALL, enables the `vector` extension.
- Opens remote access: `listen_addresses = '192.0.2.201,localhost'` and a
  `pg_hba.conf` line allowing `192.0.2.200/32` with `scram-sha-256`. So only
  the app container may connect, over the LAN.

**`provision`** (app host base):
- Creates the `app` user with passwordless sudo.
- Installs core packages, **Python 3.13** (deadsnakes PPA), **Node.js 22**
  (NodeSource), Redis, Nginx (both enabled + started), and **uv** for the
  `app` user.

**`deploy`** (initial app bootstrap — *not* ongoing deploys):
- Generates an ed25519 **deploy key** for `app`, adds GitHub to known_hosts.
- Clones `git@github.com:bthek1/Market_Analyzer.git` → `/home/app/stock_market`
  (bootstrap only; guarded by `creates: .git`).
- Renders the repo-root `.env` from `templates/env.j2` (see below), mode `0600`.
- On first clone only: `uv sync --no-dev`, installs gunicorn into the venv,
  `npm install` for the frontend.

**`services`**:
- Deploys four systemd units and starts/enables them:
  - `stockmarket-api` — gunicorn `core.wsgi` on `127.0.0.1:8004`, 4 workers,
    120 s timeout.
  - `stockmarket-celery` — `celery -A core worker`.
  - `stockmarket-celery-beat` — `celery -A core beat` with the
    `django_celery_beat` DatabaseScheduler.
  - `stockmarket-metrics` — `manage.py run_metrics_exporter` on `127.0.0.1:8010`,
    serving Celery task metrics from the event stream plus the DB-derived domain gauges.
    **Only enabled when `observability_enabled` is true**
    (see [observability.md](observability.md)).

  Two units carry observability-critical settings and are tagged `observability` so
  `just obs-deploy` ships them: `stockmarket-api` sets
  `Environment=PROMETHEUS_EXPORT_WORKER_PORTS=true` (without it gunicorn binds no metrics
  ports at all) and `stockmarket-celery` passes `-E` (without it the worker publishes no
  task events). Both notify a **restart**, not just a daemon-reload — `Environment=` and a
  changed `ExecStart` only take effect on restart.
- Deploys the **Nginx** site (`nginx-stockmarket.conf.j2`) and enables it,
  removes the default site, fixes permissions so Nginx can read the frontend
  `dist/` and backend `staticfiles/`.

**`webhook`**:
- Installs the `webhook` binary, writes `/etc/webhook/hooks.json`
  (`hooks.json.j2`) with an HMAC-SHA256 `trigger-rule` validating
  `X-Hub-Signature-256` against the vault `webhook_secret`.
- Copies `infra/deploy.sh` into `{{ app_dir }}/infra/deploy.sh`.
- Runs `stockmarket-webhook` systemd unit: `webhook -hooks … -port 9000 -verbose`.

### Configuration variables

**`group_vars/prod.yml`** (non-secret):
`app_dir=/home/app/stock_market`, `container_ip=192.0.2.200`,
`db_host=192.0.2.201`, `db_name=stockmarket`, `db_user=stockmarket`,
`django_settings_module=core.settings.prod`,
`github_repo_url=git@github.com:bthek1/Market_Analyzer.git`, and Ollama:
`ollama_base_url=http://192.0.2.202:11434`, `ollama_main_model=qwen3:8b`,
`ollama_classifier_model=qwen2.5:3b`, `ollama_embed_model=nomic-embed-text`.

**`vault/prod.yml`** (Ansible Vault encrypted, decrypted with `.vault_password`):
`vault_secret_key`, `vault_db_password`, `vault_anthropic_api_key`,
`vault_webhook_secret`, `vault_django_superuser_password`.

**`env.j2`** renders `{{ app_dir }}/.env` (the single repo-root file, also the systemd
`EnvironmentFile` for all three units), combining both:
`DEBUG=False`, `DATABASE_URL=postgresql://…@192.0.2.201:5432/stockmarket`,
`CELERY_BROKER_URL=redis://localhost:6379/0`,
`ALLOWED_HOSTS=192.0.2.200,stockmarket.local,localhost,127.0.0.1`,
CORS origins, Ollama vars, `VITE_API_BASE_URL` (read by `deploy.sh` for the SPA build),
and the Django superuser seed.

**Applying an env change needs a restart, not just an apply.** The `services` role reloads
systemd when a unit file changes, but systemd only reads `EnvironmentFile` at process start -
so a re-rendered `.env` is invisible to the running gunicorn/celery processes. When the file
moved to the repo root (issue #4), all three units picked up the new path in their unit files
while still running the *old* environment until they were restarted by hand. The risk is not
the failure, it is the delay: the change lands silently at the next deploy or reboot, far from
the edit that caused it. After any `env.j2` change:

```bash
ansible stockmarket -i infra/ansible/inventory/hosts.yml \
  -m systemd -a "name=stockmarket-api state=restarted"   # and celery, celery-beat, metrics
```

**Secrets are real values, not placeholders.** `vault_secret_key` and `vault_anthropic_api_key`
sat at the literal string `REPLACE_ME` from bootstrap until 2026-09-21, which meant prod signed
every session cookie and password-reset token with a value published in the repo's own template.
`vault_secret_key` is now a 64-char alphanumeric key; `vault_anthropic_api_key` is **empty**
(the settings default) rather than a placeholder, because a placeholder is sent as a real bearer
token and 401s at call time. Rotating the secret key invalidates all existing sessions.

### Commands (via `just`)

```bash
just ansible-ping    # connectivity check to both prod hosts
just ansible-full    # full bootstrap: site.yml (db → provision → deploy → services → webhook)
just ansible-db      # db.yml only (reconfigure PostgreSQL host)
```

All use `--vault-password-file infra/ansible/.vault_password`.

---

## CI/CD Deploy Flow

Once Pulumi + Ansible have run, **app updates never touch them**. The webhook
listener installed by Ansible handles all subsequent deploys.

```
push to main
  └─ .github/workflows/version.yml  (self-hosted runners)
       ├─ backend tests + frontend tests
       └─ both pass → bump patch tag v0.x.y
            └─ deploy.yml (on "Auto Version" completing successfully)
                 └─ runner curls http://192.0.2.200:9000/hooks/deploy
                      (HMAC-signed with WEBHOOK_SECRET)
                      └─ webhook validates signature → runs infra/deploy.sh as `app`
```

### `infra/deploy.sh` (runs on the app container)

Logs to `/home/app/deploy.log`. Steps:
1. Discard local modifications (`git checkout -- .` if dirty).
2. `git fetch origin --tags --force` → `git reset --hard origin/main`.
3. Write `VERSION` from `git describe --tags`.
4. Backend: `uv sync --no-dev`, `manage.py migrate --noinput`,
   `manage.py collectstatic --noinput`.
5. Frontend: `npm ci --prefer-offline`, `VITE_API_BASE_URL=http://192.0.2.200 npm run build`.
6. `systemctl restart stockmarket-api stockmarket-celery stockmarket-celery-beat`.
7. After a 5 s pause (so celery-beat re-inserts its system tasks),
   `manage.py sync_scheduled_tasks`.

Watch it live:

```bash
just deploy-log      # ssh app@stockmarket "tail -f /home/app/deploy.log"
```

**GitHub repo secret required:** `WEBHOOK_SECRET` — must match
`vault_webhook_secret` in the Ansible vault (the HMAC key the webhook validates).

**Deliberately not in this pipeline: the graphify code graph.** `deploy.sh` has no
graphify step, and `graphify-out/` is gitignored, so `/code-graph` in production
always renders its "not built yet" empty state. The graph is a local developer aid
built by a post-commit hook on a workstation; generating it on the app container
would add build time and an LLM dependency for no runtime benefit. If it is ever
wanted in prod, the honest options are committing a pruned `graph.json` as a real
artefact or building it in CI — both are separate decisions.

---

## Request path in production

```
Browser
  └─ Nginx :80 (192.0.2.200)
       ├─ /            → static frontend  {{app_dir}}/frontend/dist  (SPA fallback to index.html)
       ├─ /api/        → gunicorn 127.0.0.1:8004  (Django REST API)
       ├─ /admin/      → gunicorn 127.0.0.1:8004
       └─ /static/     → {{app_dir}}/backend/staticfiles/
gunicorn (stockmarket-api)
  ├─ PostgreSQL @ 192.0.2.201:5432  (stockmarket-db, pgvector)
  ├─ Redis @ localhost:6379           (Celery broker)
  └─ Ollama @ 192.0.2.202:11434     (LLM + embeddings)
Celery worker (stockmarket-celery) + beat (stockmarket-celery-beat)
  └─ same DB / Redis / Ollama
```

---

## First-time bring-up (end to end)

```bash
# 1. Provision containers on Proxmox
just pu-preview       # review
just pu-up            # creates VMID 200 (app) + 201 (db)

# 2. Configure both machines (once)
just ansible-ping     # confirm SSH reachability
just ansible-full     # db → provision → deploy → services → webhook

# 3. From here on, deploys are automatic on push to main (CI/CD → webhook).
#    Manual re-bootstrap of a role: re-run the relevant playbook, e.g. just ansible-db.
```

## Where secrets live (never commit)

| Secret store | Path | Contents |
|---|---|---|
| Pulumi | `infra/pulumi/Pulumi.prod.yaml` (encrypted) + `infra/pulumi/.passphrase` | Proxmox API token, container password, SSH key |
| Ansible Vault | `infra/ansible/vault/prod.yml` | Django secret key, DB password, Anthropic key, webhook secret, superuser password |
| Vault password | `infra/ansible/.vault_password` | Key to decrypt the vault (gitignored) |
| GitHub | repo secret `WEBHOOK_SECRET` | HMAC key matching `vault_webhook_secret` |
