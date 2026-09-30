# Observability — Grafana + Prometheus + Loki + Tempo + Alloy

Metrics, logs and traces for the Market Analyzer. Metrics and logs came from
[issue #2](https://github.com/bthek1/Market_Analyzer/issues/2); tracing is
[issue #5](https://github.com/bthek1/Market_Analyzer/issues/5), which supersedes that
issue's decision to leave Tempo out.

**Tracing status (2026-09-23): ALL FIVE PHASES built, deployed and verified.** Tempo runs on
`.208`, Alloy accepts OTLP on the app host, Django/Celery/psycopg/redis/httpx are
auto-instrumented, and the LLM calls and agent runs carry manual spans. It ships **off**
(`OTEL_TRACES_ENABLED` defaults to `False`) and is enabled in prod through Ansible.
Span metrics drive a `Domain / Tracing` dashboard, and exemplars link a latency
spike to the trace behind it.

```
stockmarket      .200   Alloy ── journald, node + redis exporters ───────────┐
                              └─ OTLP receiver :4317/:4318 (loopback) ───────┤ remote_write
stockmarket-db   .201   Alloy ── journald, node + postgres exporters ────────┤  + Loki push
stockmarket-obs  .208   Alloy ── journald, node exporter                     │  + OTLP export
                        docker: Grafana :3000 | Prometheus :9090             │
                                Loki :3100    | Tempo :3200 (+:4317/:4318) ◄─┘
```

---

## Why it is shaped this way

**Alloy pushes; Prometheus never scrapes outward.** The agent owns discovery locally and
remote-writes to `.208`. That keeps LAN traffic one-directional (no inbound ports opened
on the app or db box) and leaves no server-side target list to drift when an exporter is
added. The cost is that a dead host stops sending rather than reporting `up == 0` — which
is why the host-down alert counts survivors instead (see [Alerts](#alerts)).

**The server is its own container.** The app box has 4 GB and the browser agent already
budgets ~400 MB of it. A monitoring stack that dies alongside the thing it monitors is
also worth very little.

**Prometheus, not Mimir.** At three hosts, a distributed TSDB is pure overhead. Loki and
Tempo both run single-binary with a filesystem store for the same reason. Mimir is
explicitly out of scope — it solves multi-tenancy and horizontal scale this install
does not have.

**Everything is gated** on `observability_enabled` in `infra/ansible/group_vars/prod.yml`
(default `false`) — the same opt-in pattern as `browser_agent_enabled`.

---

## Layout

| Path | What |
|---|---|
| `infra/observability/` | The server stack: compose, Prometheus/Loki/Tempo config, Grafana provisioning, dashboards |
| `infra/ansible/roles/observability/` | Grafana Alloy agent (all hosts) |
| `infra/ansible/roles/monitoring/` | Docker + the stack on `.208`, via `observability-stack.service` |
| `backend/core/logging.py` | JSON formatter, request-id ContextVar, logging filter |
| `backend/core/middleware.py` | `RequestIDMiddleware` |
| `backend/core/tests/test_observability_assets.py` | Asserts the config invariants that fail silently |

Dashboards and alert rules are **checked into the repo** and mounted read-only, so a
rebuilt container comes back fully wired and every change goes through review.

---

## Commands

```bash
just obs-check      # ansible dry run (--check --diff)
just obs-deploy     # provision .208 + install/refresh Alloy everywhere
just obs-up         # start the compose stack on .208
just obs-down
just obs-restart
just obs-logs       # tail all four server containers
just obs-agents     # is Alloy alive on every host?
just obs-verify     # run every dashboard panel's query against the live Prometheus
just obs-trace-test # push one OTLP span through Alloy and read it back via Grafana
```

`systemctl restart observability-stack` on `.208` is equivalent to a compose recreate.

---

## What is collected

| Signal | Source | Host |
|---|---|---|
| CPU / memory / disk / load | `prometheus.exporter.unix` | all three |
| Redis (Celery broker) | `prometheus.exporter.redis` | stockmarket |
| PostgreSQL 16 | `prometheus.exporter.postgres` | stockmarket-db |
| Django requests / latency / DB | `django-prometheus`, ports 8005-8008 | stockmarket |
| Celery task lifecycle | `run_metrics_exporter`, port 8010 | stockmarket |
| Domain gauges (ingestion, agents, KG, Ollama) | `run_metrics_exporter`, port 8010 | stockmarket |
| Django / Celery / Beat logs | `loki.source.journal` | stockmarket |
| nginx access + error logs | `loki.source.file` | stockmarket |
| `deploy.log` | `loki.source.file` | stockmarket |

nginx is **not** a journal unit: it daemonises and writes its own files, so it is tailed
directly.

### PostgreSQL exporter credentials

A dedicated `postgres_exporter` login role holding only **`pg_monitor`** — PostgreSQL's
built-in monitoring grant, which reads statistics and settings but **not table data**.
The DSN is written to `/etc/alloy/postgres.dsn` (0640 `root:alloy`, task marked
`no_log`) and read via `local.file` with `is_secret = true`, so the password is neither
inlined in `config.alloy` nor printed by `ansible-playbook --diff` (which `just
obs-check` uses).

### Celery queue depth

From the Redis exporter's `check_keys`, which emits `redis_key_size` per key. A Celery
queue is a Redis **list**, so its length *is* the backlog — `redis_db_keys` counts keys
and would only ever tell you "a queue exists".

The live queue is literally named **`celery`**. Nothing in this project sets
`task_default_queue` or `task_routes`, and the prod worker unit passes no `-Q`, so every
task lands on Celery's built-in default queue. (The `be-celery` / `be-celery-heavy`
recipes pass `-Q default` / `-Q heavy`; those queue names are also watched so the metric
does not vanish if routing is ever introduced, but nothing publishes to them today.)

---

## Application metrics

### Django — one port per gunicorn worker

`django-prometheus` supplies request counts, status mix, latency histograms by view, and
DB query timings. Its two middleware halves are the **outermost** entries in `MIDDLEWARE`
(Before first, After last) — anything outside them is not counted in the latency they
report.

The api unit runs `--workers 4`, and each worker process owns a **separate**
`prometheus_client` registry. A single `/metrics` URL would therefore report whichever
worker happened to serve the scrape. So `PROMETHEUS_METRICS_EXPORT_PORT_RANGE =
range(8005, 8009)` gives each worker its own port, Alloy scrapes all four, and Prometheus
sums the counters. The alternative (`PROMETHEUS_MULTIPROC_DIR`) needs `--preload`, a
writable tmpfs and a worker-exit hook to reap dead PIDs.

Two settings that must **not** be in `base.py`:

- The **port range**, because binding happens in `django_prometheus`' `AppConfig.ready()`
  — every management command, every `runserver` and every pytest process would try to
  bind. `pytest -n auto` would collide outright.
- The **DB engine swap** to `django_prometheus.db.backends.postgresql`, because
  `core/settings/test.py` runs on SQLite and the wrapper is postgresql-only.

Both live in `prod.py` (dev gets a single opt-in port via
`PROMETHEUS_METRICS_PORT_ENABLED`), and `core/tests/test_prometheus_wiring.py` asserts the
test settings never acquire either. It also asserts the port range width matches the
`--workers` count in the api unit and Alloy's static target list — if those drift, a
worker's counters are dropped and every `rate()` silently under-reports.

### Celery — our own event consumer

`apps/tasks/metrics.py` plus `manage.py run_metrics_exporter`, running as
`stockmarket-metrics.service` on port 8010.

**Why not an off-the-shelf exporter.** PyPI's `celery-exporter` (OvalMoney) was last
released in **2021** and pins `celery>=4,<5`, so it cannot be installed beside this
project's Celery 5.x. The better-known danihodovic/celery-exporter ships **only** as a
Docker image, and the app container has no Docker (only `.208` does). Celery's `events`
API is a supported interface, so consuming it directly is a small amount of code with no
new dependency — `prometheus_client` arrives with `django-prometheus`.

The worker needs `-E` and the app needs `CELERY_WORKER_SEND_TASK_EVENTS` +
`CELERY_TASK_SEND_SENT_EVENT`; without all three the event stream carries worker
heartbeats but no task lifecycle, so every task metric reads zero. `-E` is left on
unconditionally — with no consumer the events go to an exchange with no bound queue and
are discarded, which is cheaper than making a metrics toggle require a worker restart.

It runs as **its own process**, not inside gunicorn: the event stream needs one
persistent broker connection rather than four, and phase 4's DB-derived gauges must be
computed by exactly one process or they are multiplied by the worker count.

Event handling (`handle_event`) is separated from the connection loop so tests can drive
it without a broker, and it **never raises** — losing a long-lived exporter because one
malformed event arrived is far worse than dropping a data point. The only label is the
task name, bounded by the number of `@shared_task` functions; task ids and hostnames are
deliberately absent.

Runtime histogram buckets run to 600s rather than `prometheus_client`'s default 10s
ceiling: a yfinance sync or an LLM agent run takes tens of seconds, so the default would
put nearly every real task in `+Inf`.

## Domain metrics

`apps/tasks/collectors.py` — a prometheus_client **custom collector** registered into the
same `run_metrics_exporter` process. Values are computed when Prometheus scrapes, not
cached and refreshed on a timer, so a gauge can never be stale relative to the scrape
that reported it.

It **must** run in exactly one process. "Companies with a stale snapshot" is a property
of the database, not of the process reporting it; emitted from all four gunicorn workers
it would be summed to four times the truth. That is why it lives in
`stockmarket-metrics.service` and does not go through django-prometheus at all.

| Area | Gauges |
|---|---|
| Ingestion | `stockmarket_companies`, `_companies_unbootstrapped`, `_sync_fresh_companies{sync_type}`, `_sync_oldest_age_seconds{sync_type}` |
| Agents | `stockmarket_agent_runs{kind,status}`, `_agent_runs_stuck{kind}`, `_browser_runs{stop_reason}` |
| Knowledge graph | `stockmarket_kg_concepts`, `_kg_edges`, `_kg_max_concepts`, `_kg_concepts_awaiting_rerank` |
| Ollama | `stockmarket_ollama_up` |

Sync freshness reports the **oldest** company per type, not an average — one ticker stuck
three days behind is the signal, and a mean over 500 companies would bury it.

`stockmarket_kg_max_concepts` exports the configured cap as its own series so "how close
to the ceiling" is a ratio of two live values; hard-coding `KG_MAX_NODES` in the alert
would silently invalidate it the moment the setting changed.

### Every section is individually guarded

`REGISTRY.collect()` iterates collectors and an exception propagates out of the **whole**
scrape. An unguarded failure in one query would therefore blank every other metric too —
including the ones that would tell you why. Each section is wrapped, and the guard's own
logging uses `getattr(section, "__name__", repr(section))` because an exception raised
*inside* the except block escapes the guard entirely.

### Why there is no per-call Ollama latency metric

The plan called for latency and error rate instrumented in
`llm_analysis/services.py`. LLM calls happen in **both** gunicorn workers and Celery
prefork **children**, and a child process' registry is unreachable without
`PROMETHEUS_MULTIPROC_DIR`. A metric covering only the web half would be worse than none,
because it would look complete — and a lot of LLM work (AI summaries, knowledge-graph
expansion) runs in Celery.

Instead: `stockmarket_ollama_up` is probed at scrape time from the exporter, which is
complete and is what the "Ollama unreachable" alert needs; per-call cost is visible
through `celery_task_runtime_seconds` and the agent run gauges, both of which cover every
caller.

The one runtime counter that *is* instrumented is
`stockmarket_browser_rejected_total`, incremented where the browser agent's
`BoundedSemaphore(1)` refuses a run. A rejected run creates no `AgentRun` row, so this is
the only trace it leaves — it cannot be recovered from the database afterwards. It lives
in the web process, which is where browser runs start, so the per-worker ports export it.

## Logging

One JSON object per line on stdout → systemd journal → Alloy → Loki.
`core/logging.py` is the formatter; `LOG_FORMAT=console` swaps in a readable single line
for local development. Caller `extra={...}` fields are merged into the line, so
`logger.info("synced", extra={"symbol": "AAPL"})` is queryable as a field.

The formatter **never raises**: a serialisation failure degrades to a still-parseable
line carrying `logging_error`, because a formatter that throws turns one bad `extra=`
into a stderr traceback on every subsequent log call.

### Cardinality — the rule that actually matters

Alloy labels stay at `{host, unit, job, level}`. Ticker symbols, user UUIDs, `AgentRun`
ids and concept slugs go in the **JSON body** and are queried with `| json | field="x"`
at zero index cost. An unbounded label value creates one Loki stream per value and is the
standard way to kill a small Loki install.

### Correlation ids

nginx mints `$request_id`, logs it in its JSON access log, and forwards it as
`X-Request-ID`. `RequestIDMiddleware` adopts a well-formed inbound value or mints a
uuid4, binds it to a ContextVar for the request, and echoes it on the response. The Loki
datasource carries a derived field that pivots one log line into every line from the same
request.

The inbound header is **sanitized** (`[A-Za-z0-9_-]{1,64}`) before use: it lands in both
log lines and a response header, so it is an injection vector on two paths — a newline
would forge a log line, a CR would split the response.

Note that `proxy_set_header X-Request-ID $request_id` **replaces** any client-supplied
value, so in production behind nginx the middleware's "honour an inbound id" path is
never exercised — every id originates at the edge. That is the safer default (a
client-chosen id is untrusted), but it does mean cross-service correlation from outside
the LAN would need nginx changed to `$http_x_request_id` with a fallback. The middleware
keeps the inbound path for direct-to-gunicorn calls and for tests.

**Three places the id does not reach:**

1. `StreamingHttpResponse` bodies are consumed *after* middleware returns — every SSE
   agent endpoint.
2. `services.stream_in_background` drives its workflow on a daemon thread that does not
   inherit the context.
3. Django's `BaseHandler.get_response` logs every 4xx/5xx *after* the middleware chain
   returns.

(3) was a real bug, found by probing prod. It is fixed: `RequestIDFilter` falls back to
the `request` object Django puts in the record's `extra`, where the middleware already
stamped the id. (1) and (2) remain — those runs are correlated by `AgentRun.id` instead,
which is persisted and already in the SSE payloads.

---

## Dashboards

Nine, in the "Stock Market" folder: **Hosts**, **PostgreSQL**, **Redis**, **Django**,
**Celery**, **Ingestion** and **Agents** (8 panels each), plus **Tracing** (issue #5)
and **Load Testing** (issue #12, below).

Conventions, applied deliberately:

- A single current value is a **stat tile**, never a one-bar chart.
- Trends are 2px single-axis lines with a crosshair tooltip. **No dual-axis panels** —
  two y-scales invent a correlation out of an arbitrary alignment. "Connections vs
  max_connections" works because both series are a connection count, so the headroom
  reads as the gap between the lines.
- Status colours (green/yellow/red) are reserved for **thresholds** and never used to
  tell series apart. Identity uses the classic categorical palette in fixed order.
- A legend appears only where a panel has more than one series; a single-series panel is
  named by its title.

UI edits are allowed but are overwritten on restart — export the JSON back into
`infra/observability/grafana/dashboards/` to keep a change.

### Load Testing (issue #12)

**Load Testing** (uid `sm-loadtest`) shows k6 runs next to the server-side metrics for the
same window. See [load-testing.md](load-testing.md). Points that matter here:

- **`k6_*` series exist only during and shortly after a run.** k6 remote-writes them
  (`-o experimental-prometheus-rw`, into the same `--web.enable-remote-write-receiver`
  Alloy uses). Outside a run they go stale and have no series at all. Every one is
  declared by exact name in `verify_dashboards.py`'s `EXPECTED_MISSING`, so
  `obs-verify` stays clean between runs.
- Runs are told apart by the **`testid`** label (`<profile>-<target>-<UTC timestamp>`),
  which is also the dashboard's run picker. The server panels are *not* filtered by it,
  because they show everything the app did in the window.
- **Every dashboard has a "Load test" annotation** (`max by (testid) (k6_vus)`) that
  draws a region over each run. Without it, a load test makes the prod panels look
  like an incident. It is a Prometheus query, not a call to the Grafana annotations API,
  so the load generator needs no Grafana credential. It also can't be skipped by a run
  that aborts before `teardown()`.
- k6's trend stats (`_p95`, `_p99`, `_avg`, `_max`) are computed **over the whole run
  so far**, not over a sliding window, so they lag a sudden change. Read the knee
  off the windowed Django histogram on the same dashboard instead.
- Cardinality: k6's `url`, `vu` and `iter` system tags are switched off and every
  request carries a templated `name` tag (`/api/companies/{id}/prices/`). A test fails
  any panel that groups by or filters on those three labels.

---

## Alerts

Four rules, delivered by email through the LAN mail catcher at `192.0.2.207:1025`
(plain SMTP, no auth, no TLS — so there is no credential and nothing in the vault). The
catcher accepts mail for any recipient, so the contact point's address is a routing label
rather than a real mailbox.

| Group | Rule | Fires when |
|---|---|---|
| infrastructure | Disk above 85 percent | root filesystem on any host |
| infrastructure | PostgreSQL connections near max_connections | above 80 % |
| infrastructure | Redis memory near maxmemory | above 90 % |
| infrastructure | A host has stopped reporting | fewer than 3 hosts sending metrics |
| application | HTTP 5xx rate elevated | above 5 % for 5 m |
| application | Celery task failure rate elevated | above 10 % for 10 m |
| application | Celery queue depth sustained high | above 500 for 15 m |
| domain | Price ingestion has fallen behind | oldest price sync over 3 days |
| domain | Agent runs stuck in running | more than 2 running over an hour |
| domain | Ollama unreachable | `/api/tags` not answering for 10 m |
| domain | Knowledge graph approaching its node cap | above 90 % of `KG_MAX_NODES` |
| domain | Deploy failed | an error line in `deploy.log` |

Each uses Grafana's query → reduce → threshold shape so the notification carries the
actual number.

**Two rules have non-obvious shapes, both load-bearing:**

*Redis memory* carries `and redis_memory_max_bytes > 0`. Ubuntu's `redis.conf` sets no
`maxmemory`, so that metric is **0** and the bare ratio is `+Inf` — which is `> 90`, so
the alert would fire permanently from the moment the exporter came up. Its
`noDataState` is `OK` because an empty vector is the *normal* state.

*Host down* counts survivors (`count(up{job="unix"}) or vector(0)` with a `< 3`
threshold) rather than testing `up == 0`, because push-based collection means a dead host
stops sending rather than reporting zero. **The literal `3` must be updated when a host
is added** — a test asserts it matches the Ansible inventory.

*Both percentage rules* floor their denominator with `clamp_min`. With no traffic the
ratio is `0/0` = NaN, and a NaN threshold comparison is *undefined* rather than "do not
alert" — the floor makes a silent app read 0 %.

*Deploy failed* is the **only Loki-backed rule**. Metrics cannot see it: `deploy.sh`
emits none, and the GitHub deploy workflow reports success as soon as the webhook is
*accepted*, long before the script finishes. This rule is the only automated signal that
a deploy actually failed.

*Ollama unreachable* alerts on `NoData`, because no data means the exporter process
itself is down — at least as bad as Ollama being down.

*Queue depth* waits 15 minutes. `bootstrap_tick` and the sync dispatchers enqueue in
bursts, so a short spike is normal operation; only a backlog that does not drain matters.
Its `noDataState` is `OK` because Redis deletes an empty list, so an idle broker exports
no `redis_key_size` series at all.

---

## Testing

Nearly everything here fails **silently** in production — a typo'd datasource uid renders
as an empty panel, a mis-wired alert condition is simply never evaluated, a renamed
systemd unit just stops shipping logs, a drifted port means a scrape target nobody
notices. None of it raises. So the invariants are asserted in the test suite instead.

**`core/tests/test_observability_assets.py`** — the provisioned assets and the collection
config:

- datasource uids referenced by panels and alert rules exist
- alert conditions point at one of their own query nodes
- panels do not overlap the 24-column grid; no panel has a second y-axis; multi-series
  panels show a legend
- Alloy's journal units match the unit files the `services` role deploys
- every `job="..."` selector used downstream is one Alloy actually sets
- the host-down threshold matches the Ansible inventory
- the Postgres DSN is never inlined into the Alloy template
- **every `django_*` / `celery_*` / `stockmarket_*` metric a dashboard queries actually
  exists** in the Prometheus registry, accounting for the fact that `Counter` strips a
  trailing `_total` from the name it is given (so `Counter("django_db_errors_total")`
  registers the family `django_db_errors` and emits the sample `django_db_errors_total`)
- **the same check over the alert rules' own expressions.** This one matters more than
  the dashboard version: a panel querying a misspelled metric at least reads as empty to
  whoever opens it, but an alert rule on one evaluates cleanly, reports `health=ok` and
  stays inactive forever — indistinguishable from a healthy system
- **the two error-rate panels guard every counter with `or vector(0)`** — see "Empty is
  not zero" below. Deliberately only the error rates: for the Postgres cache-hit ratio,
  NaN while idle is the honest answer, since no reads happened for a ratio to describe

**`core/tests/test_prometheus_wiring.py`** — the django-prometheus and Celery wiring:

- the prometheus middleware pair are the outermost `MIDDLEWARE` entries
- the test settings have neither the port range nor the postgresql engine wrapper
- the port range width matches `--workers` in the api unit **and** Alloy's target list
- all three Celery event switches are on (`-E`, `CELERY_WORKER_SEND_TASK_EVENTS`,
  `CELERY_TASK_SEND_SENT_EVENT`)
- the exporter unit's `--port` matches Alloy's `celery` scrape target, binds loopback
  only, and restarts always

**`apps/tasks/tests/test_metrics.py`** — the event fold itself: each lifecycle event
increments its counter, runtime is observed, an event for an unknown task is dropped
rather than counted under a placeholder, malformed events and a raising `State` do not
propagate, the worker gauge tracks heartbeats, task name is the only label, and the
runtime buckets reach past 300s.

`pyyaml` is in the dev dependency group for the YAML parsing; CI's `uv sync` picks it up.

### What the offline tests cannot reach — `just obs-verify`

The metric-name test above covers `django_*`, `celery_*` and `stockmarket_*`, because
those families come from code this repo can import. It deliberately stops there:
`node_*`, `redis_*` and `pg_*` are emitted by Alloy's **bundled** exporters, which are
not importable from pytest, so a typo in one of those names has no offline guard.

`infra/observability/verify_dashboards.py` closes that gap from the other side — it
extracts every panel target from every dashboard and runs it against the live
Prometheus, classifying each as data / empty / all-NaN / query error. It needs the LAN
stack, so it is a **hand-run check, not a CI check**.

It immediately found `pg_stat_database_rollback` on the Postgres dashboard's
Transactions panel: postgres_exporter emits `pg_stat_database_xact_rollback`, so that
series never existed and the panel had been drawing the commit line alone since phase 2.

**An empty panel is not judged on its own**, because an idle system and a misspelled
metric look identical from the outside. `topk(5, histogram_quantile(...))` over a
histogram with no increase in the window is *empty* — `histogram_quantile` yields NaN per
series and `topk` drops NaNs — which is the exact shape of a name that does not exist. So
on empty or NaN the script asks a second question: **which of the expression's metrics
have no series at all?** That is the part idleness cannot explain, and it names the
culprit directly (`no series for pg_stat_database_rollback`) instead of pointing at a
panel.

Metrics that legitimately have no series must be declared in `EXPECTED_MISSING` with a
reason — the agent gauges (label-keyed, nothing until the first `AgentRun` row), the
Celery failure/retry counters (no observations yet), and the three django-prometheus
*After*-middleware families, which create their series on first observation and so do
not exist until the first request after a worker restart. Declaring exact **names**
rather than panels is what keeps this honest: a misspelling produces a different name, so
an entry here can never silence one.

The script itself is pinned by pytest, because a verifier that quietly checks nothing is
worse than no verifier:

- its extraction finds every target in every dashboard, and every target has a title
- no Grafana interval token survives substitution (an unexpanded `$__rate_interval` is a
  400 from Prometheus on every rate panel, which would drown the real findings)
- the response classification is right: no series → `empty`, all-NaN values → `nan`,
  a value → `ok`, a non-success payload → `error`
- **metric-name extraction drops grouping labels and aggregation operators but keeps
  CamelCase names.** Both halves are load-bearing and both were caught here rather than
  in prod: a leaked `sum`/`kind`/`method` is queried as a metric and reported as
  nonexistent, failing every panel it cannot parse; and a lowercase-only pattern skipped
  `node_memory_MemAvailable_bytes` entirely, which silently "explained" every empty panel
  on the host dashboard
- every dashboard expression yields at least one metric name — an extraction that quietly
  returned nothing would make every empty panel look explainable
- exit codes: an idle panel whose metrics all exist exits 0, a declared
  `EXPECTED_MISSING` name exits 0, an **undeclared** absent metric exits 1, and a query
  error exits 1 — an unreachable Prometheus must not read as a clean stack
- every `EXPECTED_MISSING` entry still matches a metric some panel queries, so a stale
  excuse cannot sit there silencing nothing

### Empty is not zero

A counter that has never been observed has **no series**, and a ratio whose numerator is
an empty vector is empty — so a 0 % error rate rendered as "No data", indistinguishable
from a broken query. The Django 5xx-rate and Celery failure-rate panels therefore wrap
each counter in `or vector(0)`, which is the same class of fix as the Redis alert's
`and redis_memory_max_bytes > 0`. The equivalent alert rules were already safe: they
carry `noDataState: OK`.

---

## Tracing

Added by [issue #5](https://github.com/bthek1/Market_Analyzer/issues/5). **Phases 1-2 are
deployed; phase 3 (application instrumentation) is not started**, so Tempo is currently
an empty, working store.

```
gunicorn / celery child ──OTLP──> Alloy (127.0.0.1:4317/:4318) ──batch──> Tempo (.208:4317)
  [phase 3, built, OFF]                [live]                               [live]
```

### Application side (phase 3)

`core/tracing.py` owns the provider. It is called from **explicit entry points**, never
from `AppConfig.ready()`:

| Entry point | Process | Service name |
|---|---|---|
| `core/wsgi.py` | gunicorn workers | `stockmarket-api` |
| `core/celery.py`, `worker_process_init` | each prefork **child** | `stockmarket-celery` |

- **Not `AppConfig.ready()`** — it fires in every process that calls `django.setup()`,
  including each `manage.py` during a deploy and every pytest worker. That is the exact
  trap that forced the Prometheus port range out of `base.py`.
- **Per prefork child, not the parent.** `BatchSpanProcessor` runs a background thread,
  and threads do not survive `fork()`; a provider built in the parent leaves every child
  queueing spans that are never flushed.
- **`OTEL_TRACES_ENABLED` may live in the shared `.env`**, unlike
  `PROMETHEUS_EXPORT_WORKER_PORTS` which must stay in the gunicorn unit. The difference
  is the entry points: a management command reading this value does nothing with it.
- **Sampling is `ParentBased(TraceIdRatioBased(ratio))`.** ParentBased matters more than
  the ratio — without it a sampled parent can have unsampled children, rendering as a
  trace with holes, which looks like a gap in the *system* rather than in the sampling.
- **Everything degrades to "no tracing".** Import failure, setup failure and a failing
  individual instrumentor are all caught; instrumentation must never take down a request.
- **`trace_id`/`span_id` go in the JSON log body**, never a Loki label — a trace id is
  the most unbounded value in the system. Grafana's derived field reads them back at
  query time, which is what makes a log line click through to its trace.

### Why it exists

Two gaps in the metrics/logs design are consequences of having no traces, and both close
in phase 4:

1. **No per-call Ollama latency metric.** LLM calls run in gunicorn workers *and* Celery
   prefork children, whose `prometheus_client` registries cannot be merged without
   `PROMETHEUS_MULTIPROC_DIR` — so a web-only metric would look complete while missing AI
   summaries and KG expansion. Spans have no shared-registry problem: each process
   exports independently and Tempo reassembles by trace id.
2. **Two `request_id` propagation holes** — `StreamingHttpResponse` bodies are consumed
   after middleware returns, and `stream_in_background` uses a daemon thread that does
   not inherit the ContextVar. Both are "context did not propagate", which is what OTel
   context propagation exists to solve.

### Server: Tempo on `.208`

Single-binary, filesystem-backed, `grafana/tempo:2.10.8`. Config lives in
`infra/observability/tempo/config.yml`.

- **Retention is 15d, pinned to Prometheus'** by `test_retention_matches_prometheus`,
  which parses `--storage.tsdb.retention.time` out of the compose command. If Tempo
  expired first, clicking through from a metric would land on a compacted-away trace.
- **Tempo has no `retention.size` equivalent**, so the disk guard is an *ingestion* cap
  (`rate_limit_bytes`, `max_bytes_per_trace`) rather than a size ceiling — it shares a
  100 GB disk with Prometheus and Loki.
- **`max_block_duration: 5m`** against a 30m default. At the default a finished trace
  sits unqueryable in the WAL for up to half an hour, which is indistinguishable from a
  broken pipeline exactly when you are testing the pipeline.
- **No docker healthcheck, deliberately.** The Tempo image is **distroless** — no shell,
  no `wget`, no `curl` — so a Loki-style `["CMD", "wget", ...]` probe cannot execute and
  would pin the container at `unhealthy` while it serves fine. A test asserts the
  healthcheck stays absent so nobody "fixes" the inconsistency.
- **gRPC is on 9097, not Loki's 9096**, so a stray host-network debug run cannot collide.

### Collection: Alloy

`otelcol.receiver.otlp` -> `otelcol.processor.attributes` (host) ->
`otelcol.processor.batch` (2s) -> `otelcol.exporter.otlp` -> Tempo.

- **The receiver binds `127.0.0.1` only.** The only legitimate clients are local
  processes. Spans are attacker-controlled text rendered into a UI, so a LAN-bound
  receiver would let anything on the network inject into the traces.
- **Traces are enabled on the app host ONLY, and that is load-bearing.** Tempo publishes
  `0.0.0.0:4317`/`:4318` on `.208`, and `0.0.0.0` already covers `127.0.0.1`, so an Alloy
  receiver there could not bind — and in Alloy a component that fails to start takes the
  **whole agent** down, losing that host's logs and metrics too. Three tests pin it:
  enabled on `stockmarket`, absent on `stockmarket-obs`, absent on `stockmarket-db`.
- **The `host` attribute** is the traces equivalent of `external_labels` on the Loki and
  Prometheus sinks. Three hosts push into one Tempo; without it a span's origin is lost.
- **Batching is not optional.** Unbatched, every span is its own export call — inside a
  Celery prefork child that is a network round trip in the middle of a task.
- `alloy_otlp_endpoint` resolves through `obs_host`, so the obs box's
  `obs_host: 127.0.0.1` override is honoured like the other two sinks.

### Verifying

```bash
just obs-trace-test     # push one span through Alloy, read it back through Grafana
```

Every hop fails **silently**: a wrong exporter port queues, retries and drops, logging
nothing on either box. That is why this is a recipe rather than a note.

Validate config changes against the real binaries before deploying — both accept a
config and exit non-zero on error, and both were mutation-checked when introduced:

```bash
# Tempo (image is distroless, so bake the config into a throwaway image)
tempo -config.file=/etc/tempo.yaml -config.verify=true     # note: =true, bare flag exits 2
# Alloy
alloy validate /etc/alloy/config.alloy
```

> **Do not bind-mount repo paths into a Docker daemon that cannot see them.** The local
> dev daemon runs on another host; `docker run -v $PWD/x/y.yml:...` silently created a
> *directory* named `y.yml`, clobbering the file.

### Grafana

Datasource uid `tempo`, `http://tempo:3200`, `nodeGraph` on, search streaming on (which
must match `stream_over_http_enabled` in Tempo's config — pinned by a test).

> **The datasource health API does not work for Tempo.**
> `/api/datasources/uid/tempo/health` returns `Method not implemented` — the plugin has
> no backend health check. The **Test** button proxies `/api/echo`, so the real check is
> `curl -u admin:$PW .../api/datasources/proxy/uid/tempo/api/echo` -> `echo`.

Correlation is wired **both ways** as of phase 3, because `core/logging.py` now emits
`trace_id` into the JSON body:

- **Loki -> Tempo**: a `trace_id` derived field on the Loki datasource turns any log line
  into a click-through to its trace.
- **Tempo -> Loki**: `tracesToLogsV2` queries `| json | trace_id = ...` over a ±5m
  window (a span's own window is often sub-millisecond).

`request_id` stays alongside it deliberately — it is the pivot that **always** exists,
including on the SSE streaming paths that still have no span to link to.

> **The error lines needed a rescue.** `BaseHandler.get_response` logs every 4xx/5xx
> *after* the middleware chain unwinds, so the span has ended and `get_current_span()`
> returns an invalid one — leaving the lines most worth correlating as the only ones
> with no trace. `RequestIDMiddleware` stamps `request.trace_id`/`span_id` while the span
> is live, and `RequestIDFilter` falls back to them. This is the same rescue the request
> id already needed, for the same reason. The ids are read in the **filter**, not the
> formatter: they belong to the context that emitted the record.

---

### Manual spans (phase 4)

Auto-instrumentation gives request, DB and raw-HTTP spans. These add the structure that
makes an agent run legible.

| Span | Where | Attributes |
|---|---|---|
| `agent.run` | `services.stream_in_background` | `agent.run_id`, `agent.kind`, `agent.model` |
| `ollama.chat` | `services.chat` | `llm.model`, `llm.tokens.prompt`, `llm.tokens.completion` |
| `ollama.chat_stream` | `services.chat_stream` | `llm.model`, `llm.chunks` |
| `ollama.chat_many` | `services.chat_many` | `llm.batches`, `llm.workers`, `llm.failures` |
| `ollama.embed` | `services.embed` | `llm.model`, `llm.inputs` |
| `agent.step` | two mechanisms, see below | `agent.step_order`, `agent.step_key`, `agent.step_label`, `agent.step_status` |
| `agent.tool` | `tools.run_tool` | `tool.name`, `tool.args` |

`summarise` and `analyse` are covered transitively — both call `chat`. `tools.run_tool`
is a single choke point for **six** workflows (react, plan-execute, orchestrator,
multiagent, dag, autonomous), so one span covers all of them.

A real run, as it renders in Tempo:

```
POST api/llm/parallel/                  31ms
  agent.run                         13407ms  run_id=f3ff65d7… kind=parallel
    ollama.chat_many                 3337ms  batches=3 workers=3 failures=0
    ollama.chat                      3329ms  qwen3:8b prompt=61  completion=132
    ollama.chat                      2561ms  qwen3:8b prompt=71  completion=89
    ollama.chat                      2917ms  qwen3:8b prompt=62  completion=107
    ollama.chat                     10042ms  qwen3:8b prompt=390 completion=553
```

8.8s of fan-out work inside a 3337ms parent is the wall clock proving true concurrency —
and the 31ms HTTP span against a 13.4s `agent.run` is the SSE shape exactly: the response
returns immediately, the work continues on the background thread.

**Token counts are free.** Ollama already returns `prompt_eval_count`/`eval_count` in the
body `chat` was parsing anyway. They are the closest thing to a cost signal here, and
they cover **both** the web and Celery halves — which is precisely what the Prometheus
approach could not.

#### Per-step spans use two mechanisms

The ten workflow modules do not share one shape, so neither does the instrumentation:

| Mechanism | Modules | Why |
|---|---|---|
| `tracing.step_span()` wrapping the loop body | chain, react, eval_opt, plan_execute | the step loop is in one place |
| replay from `store.update_step` | parallel, orchestrator, multiagent, dag, autonomous | they already mark a step running, then done/error, with real timestamps |

The replay path is the better one where it applies: the span carries the **step's own**
recorded duration rather than a wrapper's, and one edit in `store.update_step` covers five
modules. `router` is deliberately exempt — it persists no `AgentStep` rows, it classifies
and spawns a chain run. A structural test asserts every module is covered by one mechanism
or the other, so a new workflow cannot ship without step spans.

> **The two mechanisms are NOT equivalent, and the difference shows in the waterfall.**
> A wrapper span is open while the step runs, so the step's LLM and tool calls nest
> *inside* it (`agent.run -> agent.step -> ollama.chat`). A replayed span is created
> after the fact from stored timestamps, so its **duration is right but nothing nests
> inside it** — the step's LLM calls appear as siblings under `agent.run`. Verified in
> prod: an `orchestrator` run showed `agent.step` (5622ms) beside `ollama.chat_many`
> (5618ms) rather than containing it. Accurate per-step timing either way; causal
> nesting only from the wrapper. Converting the replay modules would mean wrapping five
> more loop bodies, which is why it was not done here.

> **`_set_attributes` takes a positional dict, never `**kwargs`.** The attribute keys
> contain dots, so they cannot be keyword arguments — passing them as kwargs raises
> `TypeError`, and a bare `except Exception: pass` swallows it, leaving the function
> emitting nothing while looking healthy. That happened here, which is why the guard in
> `record_completed_step` now warns **once per process** rather than staying silent.

> **OTel context does not cross a thread boundary, and the failure is SILENT.** The work
> succeeds; it just reparents into its own root trace, so the waterfall quietly stops
> showing the structure. Both seams — `stream_in_background`'s daemon thread and
> `chat_many`'s `ThreadPoolExecutor` — need `current_context()` + `attached(ctx)`.
>
> **Capture the context INSIDE the span you want as the parent.** Captured outside, the
> workers attach to the *caller*, and every fan-out call becomes a **sibling** of
> `ollama.chat_many` instead of a child — so the span that exists purely to group the
> fan-out contains none of it. Found in prod; the test had asserted only the parent
> span's attributes and never that children nested under it.

`tools.run_tool` **must never raise** — its docstring is the contract, and the agent
loops treat a tool error as data to reason about on the next turn. The span records the
error and still returns the `{"error": ...}` observation.

### Span metrics and exemplars (phase 5)

A trace store cannot answer "p95 over the last hour", so Tempo's **metrics_generator**
derives RED metrics from the spans passing through it and remote-writes them to
Prometheus as `traces_spanmetrics_*` and `traces_service_graph_*`. Those back the
**Domain / Tracing** dashboard (uid `sm-tracing`).

**Cardinality is the rule here too, and the cost of breaking it is higher.** Span metrics
create a series per span name per dimension combination, so only bounded attributes may
be listed as `dimensions` — `llm.model` (a handful) and `agent.kind` (ten). `agent.run_id`
must **never** appear: it is a UUID per run, it is exactly why it lives as a span
attribute (free in Tempo) rather than a label, and adding it would multiply every span
name by every run ever executed. A test enforces the exclusion list.

**Dimension names arrive with dots replaced by underscores** — `llm.model` is queried as
`llm_model`. Querying the dotted form is a label that never exists, so the panel is
simply always empty.

**Exemplars need three switches, and missing any one fails silently:**

| Switch | Where | If missing |
|---|---|---|
| `send_exemplars: true` | Tempo `remote_write` | nothing is sent |
| `--enable-feature=exemplar-storage` | Prometheus command | the write succeeds, the exemplar is dropped |
| `exemplarTraceIdDestinations` | Grafana prometheus datasource | the dot renders, the click goes nowhere |

The exemplar label is Tempo's and it is **camelCase `traceID`**, not the `trace_id` our
log bodies use. Getting it wrong is the quietest failure of the three: Grafana still
draws the dot.

> **PromQL regexes need two layers of escaping, and each direction fails differently.**
> A PromQL string literal uses Go escaping, so `\.` is an *invalid escape* and Prometheus
> answers **HTTP 400** — not an empty result, a hard error only `obs-verify` would see.
> The regex a panel needs is `ollama\\..*` in PromQL text, which is `ollama\\\\..*` in
> the JSON file, because JSON escapes each backslash again. Too many backslashes is the
> opposite failure: a regex matching a literal backslash, which matches nothing and reads
> as an idle panel. Both directions are mutation-tested.

### Alerting stays metric-based

Span metrics could back an alert and deliberately do not. Tracing ships **off**, so such
a rule would sit permanently in NoData wherever it is not enabled; span metrics depend on
the whole pipeline (app -> Alloy -> Tempo -> generator -> remote_write), so the rule would
fire for pipeline faults rather than application ones; and the existing 12 rules already
cover the same failures from a shorter causal chain. **Traces are for diagnosis, metrics
for alerting.** A test pins the rule count at 12 and asserts no rule queries
`traces_spanmetrics_*`.

### Verify against a real trace, not just tests

Three defects on issue #5 were tested, reviewed and wrong, and all three were obvious in
a single prod waterfall:

| Defect | How it looked |
|---|---|
| Instrumenting after `get_wsgi_application()` | psycopg spans arrived as orphan **root** traces; no request span |
| 4xx/5xx log lines | `request_id` present, `trace_id` null — the error lines uniquely uncorrelated |
| `chat_many` context captured outside the span | fan-out calls rendered as siblings of their own grouping span |

None of them raised anything. Two of them looked *partially* healthy, which is worse
than a clean failure. `just obs-trace-test` covers the transport; the application spans
need a real agent run.

---

## Deploying

This is **machine bootstrap**, like the rest of `infra/ansible` — `deploy.sh` is
untouched and CI builds nothing here. A code push updates the Django half only; the
nginx, systemd and Alloy halves need an Ansible run.

### Current status

| Host | State |
|---|---|
| `stockmarket` (.200) | Alloy + metrics exporter live; nginx JSON logs and `X-Request-ID` applied |
| `stockmarket-db` (.201) | Alloy + `postgres_exporter` role live |
| `stockmarket-obs` (.208) | Grafana + Prometheus + Loki + Tempo live; Alloy live |

**Verified end to end on 2026-09-22**: all targets `up=1` (including four `django`
targets, one per gunicorn worker), 7 dashboards and 12 alert rules provisioned, and a
404 traced from Django's JSON log through the journal into Loki with its `request_id`
intact — which also confirms the phase-1 fix for 4xx lines logged outside the middleware
chain.

**Panel and alert verification, 2026-09-23** — `just obs-verify` reports 0 unexplained
panels across all 65 targets. Generated traffic landed in Prometheus with the counters
summing **exactly** across the four worker registries (24, then 54, then 153 requests
sent = 153 counted), a dispatched Celery task appeared as
`celery_task_succeeded_total`, and the 12 rules all evaluate with `health=ok`. The email
contact point was exercised through Grafana's test endpoint (`status: ok`), and the
host-down rule was **fired for real** by stopping Alloy on `.208`: `inactive` → `firing`
after the 5 m staleness window plus its 5 m `for`, routed to the `email` receiver, then
back to `inactive` once Alloy was restarted and the third `unix` target returned.

Redis was deliberately **not** stopped to fire an alert, despite being the obvious
candidate — it is the Celery broker, so it would have taken the app down. The host-down
rule proves the same path (rule → notification policy → contact point) at no cost.

### First-time setup

1. **Done** — `vault_grafana_admin_password` and `vault_postgres_exporter_password` are
   in `infra/ansible/vault/prod.yml`. Both are referenced unconditionally once enabled, so
   a missing one fails the run loudly rather than provisioning something with a default
   password. Retrieve a value with:
   `ansible-vault view infra/ansible/vault/prod.yml --vault-password-file infra/ansible/.vault_password`
   (the Grafana one is the admin login for `http://192.0.2.208:3000`, user `admin`).

   Both are generated from a URL-safe alphabet on purpose: the exporter password is
   interpolated into a DSN (`postgresql://postgres_exporter:PASSWORD@...`), where `@ : /
   ? # %` would break parsing, and the Grafana one lands in an env file where `$` risks
   interpolation.
2. **Done** — `observability_enabled: true` in `group_vars/prod.yml`.
3. Create the container: `just pu-preview`, **read the output**, then `just pu-up`.
   The preview must show `+ 1 to create` (`stockmarketObs`) and `3 unchanged`; an apply
   touching `console` / `startOnBoot` has restarted the existing containers before.
4. `just obs-deploy`.

### What `just obs-deploy` covers

`--tags observability` selects more than the agent role — it has to, or it would deliver
a half-configured feature. The tagged set is:

| Role | Tasks |
|---|---|
| `db` | the `postgres_exporter` login role, its `pg_monitor` grant, its `pg_hba` entry |
| `observability` | the whole role (Alloy on every host) |
| `monitoring` | the whole role (the server stack on `.208`) |
| `services` | the api unit (carries `PROMETHEUS_EXPORT_WORKER_PORTS`), the celery unit (carries `-E`), the metrics unit and its enablement, the nginx JSON log format and site config |

Two of those are load-bearing in a non-obvious way, and both have tests:

- **The api unit** sets `Environment=PROMETHEUS_EXPORT_WORKER_PORTS=true`, which
  `prod.py` gates the per-worker metrics ports on. Untagged, `obs-deploy` ships the gated
  settings **without** the flag that enables them, gunicorn binds no metrics ports at all,
  and every Django metric silently disappears. This reached production once.
- **The db role's exporter tasks.** Untagged, `obs-deploy` installs the Postgres exporter
  without creating the role it authenticates as — a silently empty Postgres dashboard.

The recipe passes **`--force-handlers`**. A play that *fails* discards its pending
handlers, so a unit file can be rewritten on disk while the running process keeps its old
command line — and the next run, seeing the file already correct, notifies nothing and
never fixes it. That happened for real with the celery `-E` flag: unit file right, process
wrong, and every Celery metric would have read a plausible zero.

### `obs-check` is a diff preview, not a validation

On a host that is not already provisioned, `--check` necessarily stops at the first task
that depends on a previous task's effect:

- it does not write the Grafana apt repo, so `apt: name=alloy` reports
  `No package matching 'alloy' is available` (the package is real — `alloy`, currently
  1.19.x, in Grafana's stable repo);
- it does not create the `postgres_exporter` role, so the `pg_monitor` grant reports
  `Role postgres_exporter does not exist`.

Both are artifacts of the dry run. `obs-check` is useful as a **diff preview for an
already-provisioned host**, not as a gate before the first deploy.

### The exporter job labels must be forced

Alloy's `prometheus.exporter.*` components attach their **own** `job` label —
`integrations/unix`, `integrations/redis`, `integrations/postgres` — and a target's
existing `job` label **beats** `prometheus.scrape`'s `job_name`. Setting `job_name` alone
does not rename it.

This was found only in production: `up{job="integrations/unix"}` was arriving while the
host-down alert selected `up{job="unix"}`, matched nothing, fell through to `vector(0)`
and would have fired permanently. Each exporter is now routed through a
`discovery.relabel` that sets the label explicitly, and a test asserts it.

The lesson generalises: `test_every_job_label_used_downstream_is_one_the_agent_sets`
passed throughout, because it compared queries against the `job_name` values in the
template — i.e. against the assumption, not against what Alloy actually emits.

### Operational notes

- **pg_hba changes reload, they do not restart.** PostgreSQL re-reads `pg_hba.conf` on
  SIGHUP; a restart would drop every application connection for an auth-rules change.
  (`listen_addresses` genuinely does need a restart, which is why that handler still
  exists.)
- **`Environment=` only applies on a restart.** A `daemon-reload` leaves the running
  process with its old environment, so the api unit notifies `restart api`, not just
  `reload systemd`.
- **A change to `deploy.sh` first takes effect on the deploy *after* the one that ships
  it.** The webhook executes `infra/deploy.sh` from the working tree, and bash reads a
  script as it runs — so the `git pull` inside it rewrites the file that is already
  executing, and the pulled version's new steps are not run. The metrics-exporter
  restart block landed in the same commit as the deploy that pulled it, so
  `stockmarket-metrics` kept serving an **11-hour-old process with no `DomainCollector`
  registered**: `celery_*` metrics were present, every `stockmarket_*` domain metric was
  silently absent, and the exporter's journal still carried the pre-gate
  "no available ports in supplied range" warning that proved which code it was running.
  One `systemctl restart stockmarket-metrics` fixed it and all 27 domain samples
  appeared. The lesson: after changing `deploy.sh`, either run the affected step by hand
  or trigger a second deploy — and when a metric is missing, check the exporter's start
  time before suspecting the query.
- **A seven-week-old interrupted dpkg blocked the first deploy.** `apt` refused with
  "dpkg was interrupted" even though `dpkg --audit` was clean and nothing held the lock;
  the cause was stale transaction journal files in `/var/lib/dpkg/updates/`.
  `dpkg --configure -a` cleared it. Worth knowing because it would break *any* apt
  install on that host, including the browser-agent provision.

---

## Not covered

- **Manual spans for the LLM and agent workflows.** Phase 3 gives auto-instrumented
  Django/Celery/DB/HTTP spans (so Ollama calls appear as httpx spans in *both* the web
  and Celery halves), but the per-workflow structure — a span per agent step, sibling
  spans for a `chat_many` fan-out, context propagated into `stream_in_background`'s
  daemon thread — is phase 4 of
  [issue #5](https://github.com/bthek1/Market_Analyzer/issues/5).
- **Mimir.** Deliberate, not pending. Prometheus is right for three LAN hosts at
  15d/30GB.
- **Proxmox host metrics.** In an unprivileged LXC the unix exporter reports the
  *container's* `/proc`, not the hypervisor's. Real hardware metrics need Proxmox's own
  `pve-exporter`.
- **Per-call LLM latency** — see "Why there is no per-call Ollama latency metric" above.
- **Agent run duration as a histogram** — the gauges count runs by kind and status, but
  there is no latency distribution. It would need instrumenting where a run reaches a
  terminal status, which happens on a daemon thread in the web process *and* in Celery,
  so it has the same prefork problem.
