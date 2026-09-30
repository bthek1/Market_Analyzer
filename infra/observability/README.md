# Observability server (Grafana + Prometheus + Loki + Tempo)

The server half of issue #2. Runs as three Docker containers on **stockmarket-obs**
(`192.0.2.208`, VMID 208, created by `infra/pulumi`). The collection half is Grafana
Alloy, installed on every host by `infra/ansible/roles/observability`.

| Service | Port | Purpose |
|---|---|---|
| Grafana | 3000 | UI, provisioned datasources + dashboards |
| Prometheus | 9090 | metrics, 15 d retention, remote-write receiver |
| Loki | 3100 | logs, 30 d retention, filesystem TSDB |

## Deploying

The stack is not applied by the app's CI/CD - it is machine bootstrap, like everything
else in `infra/ansible`:

```bash
just obs-deploy        # provision .208 + install Alloy everywhere (needs observability_enabled: true)
just obs-up            # start/refresh the compose stack on .208
just obs-down          # stop it
just obs-logs          # tail all four services
```

On the host the stack is owned by `observability-stack.service`, so
`systemctl restart observability-stack` is equivalent to a compose recreate.

## Signal flow

```
app/db host                                   stockmarket-obs
  journald ------\                              +-> Loki   <- loki.write
  nginx logs -----> Grafana Alloy --------------|
  deploy.log ----/                              +-> Prometheus <- prometheus.remote_write
  exporters -----/
```

Alloy pushes; Prometheus does not scrape outward. That keeps LAN traffic
one-directional and means there is no target list on the server to drift.

## What is collected

| Source | Exporter | Host |
|---|---|---|
| CPU / memory / disk / load | `prometheus.exporter.unix` | all three |
| Redis (Celery broker) | `prometheus.exporter.redis` | stockmarket |
| PostgreSQL 16 | `prometheus.exporter.postgres` | stockmarket-db |
| journald, nginx, deploy.log | Loki sources | see site.yml |

The Postgres exporter authenticates as a dedicated `postgres_exporter` role holding only
`pg_monitor` - PostgreSQL's built-in monitoring grant, which can read statistics but not
table data. Its DSN is written to `/etc/alloy/postgres.dsn` (0640) and read via
`local.file`, so the password is neither inlined in `config.alloy` nor echoed by
`ansible-playbook --diff`.

Celery queue depth comes from the Redis exporter's `check_keys`, which reports
`redis_key_size` per key. Celery queues are Redis LISTS, so the list length *is* the
backlog - `redis_db_keys` counts keys and cannot tell you this.

## Dashboards and alerts

Three dashboards in `grafana/dashboards/` (`host`, `postgres`, `redis`), provisioned into
the "Stock Market" folder. Four alert rules in `grafana/provisioning/alerting/rules.yml`:
root disk > 85 %, Postgres connections > 80 % of `max_connections`, Redis memory > 90 % of
`maxmemory`, and fewer than three hosts reporting.

That last one counts survivors rather than testing `up == 0`, because collection is
**push**-based: a dead host stops sending rather than reporting zero, so `up == 0` would
never fire. **If you add a host, update the `3` in that rule.**

Alerts deliver by email through the LAN mail catcher at `192.0.2.207:1025` (plain SMTP,
no auth), configured via the `GF_SMTP_*` block in `docker-compose.yml`. The catcher
accepts mail for any recipient, so the contact point's address is a routing label rather
than a real mailbox.

`backend/core/tests/test_observability_assets.py` asserts the cross-file invariants -
datasource uids referenced by panels and alert rules actually exist, alert conditions
point at their own nodes, panels do not overlap, no panel has a second y-axis. These
files fail silently in production, so they are checked in CI instead.

## Conventions that matter

- **Labels are an index.** Alloy labels stay at `{host, unit, job, level}`. Ticker
  symbols, user UUIDs, `AgentRun` ids and concept slugs go in the JSON log body, where
  `| json | field="value"` filters them at query time for free. An unbounded label value
  creates a new Loki stream per value and is the standard way to melt a small install.
- **Dashboards live in the repo** under `grafana/dashboards/`. UI edits are allowed but
  are overwritten on restart - export the JSON back into the repo to keep a change.
- **Nothing here is authenticated except Grafana.** Prometheus' remote-write receiver and
  Loki's push endpoint are open to the LAN because the agents need them. Do not expose
  this box beyond the private network.

## Useful queries

```logql
{unit="stockmarket-api.service"} | json | level="ERROR"
{unit="stockmarket-celery.service"} | json | logger=~"apps.companies.*"
{job="deploy"}                                          # deploy.sh output
{job="nginx"} | json | status >= 500
```

Click the `request_id` link on any app log line to pull every line from that request.
