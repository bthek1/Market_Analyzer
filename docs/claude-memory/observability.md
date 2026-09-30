---
name: observability
description: "Grafana + Prometheus + Loki + Tempo + Alloy stack (issues #2, #5) — push-based collection, the gotchas that make each alert rule non-obvious, and what is deliberately not covered"
metadata:
  type: project
---

Metrics + logs for the Market Analyzer, added by
[issue #2](https://github.com/bthek1/Market_Analyzer/issues/2). All four phases are built and **FULLY DEPLOYED**
(2026-09-22): all three hosts up, 7 dashboards + 12 alert rules live, verified end to end.
Full design: `docs/project_docs/observability.md`.

**Tracing is now IN scope** — [issue #5](https://github.com/bthek1/Market_Analyzer/issues/5)
supersedes issue #2's decision. Tempo + the Alloy OTLP pipeline are DEPLOYED (2026-09-23,
phases 1-2). Phases 3 (`core/tracing.py`, `trace_id` in the log body, bidirectional
Grafana correlation) and 4 (manual spans on the Ollama calls and agent runs) are BUILT,
DEPLOYED and verified against a live agent run. Ships OFF by default
(`OTEL_TRACES_ENABLED=False`); prod enables it via Ansible. Phase 5 (Tempo span metrics -> `Domain / Tracing`
dashboard + exemplars) is DEPLOYED and verified. **ALL FIVE PHASES COMPLETE.** Mimir stays
out of scope deliberately.

**Why:** the deployment had no observability at all — no `LOGGING` dict anywhere, no
metrics, and diagnosing anything meant `ssh` plus `journalctl`.

**How to apply:**

- **Collection PUSHES.** Alloy on each host remote-writes to `.208`; Prometheus never
  scrapes outward. One-directional LAN traffic, no server-side target list. The
  consequence that bites: a dead host stops sending rather than reporting `up == 0`, so
  `up == 0` can never fire — the host-down alert counts survivors against a hard-coded
  host count instead.
- **Everything is gated** on `observability_enabled` (default `false`), like
  `browser_agent_enabled`. Needs `vault_grafana_admin_password` and
  `vault_postgres_exporter_password` in the vault first.
- **`deploy.sh` does not run Ansible.** A push updates the Django logging half only; the
  nginx and Alloy halves need `just obs-deploy` / the `services` role.
- **Cardinality is the rule.** Loki labels stay at `{host, unit, job, level}`. Tickers,
  user UUIDs and `AgentRun` ids go in the JSON body, queried with `| json | field="x"`.
- **Three gotchas already paid for:**
  1. Django logs every 4xx/5xx *after* the middleware chain returns, so the request-id
     ContextVar is already reset — error lines, the ones worth correlating, silently lost
     their id. `RequestIDFilter` now falls back to the `request` in the record's `extra`.
  2. Ubuntu's redis sets no `maxmemory`, so `redis_memory_max_bytes` is 0 and a bare
     ratio is `+Inf` — an unguarded alert fires forever.
  3. The live Celery queue is named **`celery`**, not `default`/`heavy`. Nothing sets
     `task_default_queue` or `task_routes` and the prod unit passes no `-Q`. Watching the
     wrong key reports 0 backlog forever.
  4. `PROMETHEUS_METRICS_EXPORT_PORT_RANGE` and the `django_prometheus` DB engine must
     stay OUT of `base.py` - the first binds ports in `AppConfig.ready()` (every pytest
     process, and `-n auto` collides), the second is postgresql-only while tests run on
     SQLite.
  5. PyPI's `celery-exporter` is unusable (2021, pins `celery<5`) and danihodovic's is
     Docker-only, so Celery metrics are our own event consumer in `apps/tasks/metrics.py`.
     It needs `-E` AND both `CELERY_*_SEND_*_EVENT` settings or every metric reads zero.
  6. `django_prometheus` binds ports in `AppConfig.ready()`, i.e. in EVERY process calling
     `django.setup()`. `PROMETHEUS_EXPORT_WORKER_PORTS` is therefore set only in the
     gunicorn unit via `Environment=`, never in the shared `.env` - otherwise a Celery
     worker claims 8005 and Alloy scrapes it believing it to be a web worker. Exhaustion
     only WARNS, so it fails silently.
  7. There is deliberately NO per-call Ollama latency metric: LLM calls run in Celery
     prefork CHILDREN whose registries are unreachable without `PROMETHEUS_MULTIPROC_DIR`,
     and a web-only metric would look complete while missing AI summaries and KG expansion.
     `stockmarket_ollama_up` is probed at scrape time instead.
  8. Domain gauges are a custom collector in ONE process (`apps/tasks/collectors.py`);
     from four gunicorn workers a DB-derived gauge would be 4x the truth. Every section is
     guarded because `REGISTRY.collect()` propagates an exception out of the whole scrape.
  9. **`--tags observability` must span four roles.** The api unit carries
     `PROMETHEUS_EXPORT_WORKER_PORTS`; untagged, obs-deploy shipped the gated settings
     without the flag and gunicorn bound NO metrics ports - every Django metric vanished
     in prod. Same class: the db role's `postgres_exporter` tasks.
 10. **A FAILED Ansible play discards its pending handlers**, so a unit file can be right
     on disk while the running process keeps its old command line, and the next run
     notifies nothing. Hit for real with celery `-E`. `obs-deploy` now uses
     `--force-handlers`, and `Environment=` changes notify a RESTART (a daemon-reload
     leaves the old environment in place).
 11. **`.203` is a Frigate NVR, not free.** The obs container is `.208`/VMID 208. Free LAN
     addresses as of 2026-09-22: `.198`, `.199`, `.204`, `.208`-`.215`; `.205`/`.206` are
     in use by unidentified hosts and `.207` is the mailpit catcher alerts go through.
 12. **Alloy exporters attach their own `job` label** (`integrations/<name>`) which BEATS
     `prometheus.scrape`'s `job_name`. Each exporter needs a `discovery.relabel` forcing
     the short name, or every `job="unix"` query matches nothing. Found only in prod - the
     test that "checked" it compared against the template's `job_name`, i.e. the
     assumption rather than what Alloy emits.
 13. **A `deploy.sh` change takes effect one deploy late.** The webhook runs
     `infra/deploy.sh` from the working tree and bash reads a script as it executes, so
     the `git pull` inside it rewrites the file already running. The metrics-exporter
     restart block shipped in the same commit as its own deploy, leaving
     `stockmarket-metrics` on an 11-hour-old process with no `DomainCollector`: `celery_*`
     present, every `stockmarket_*` silently absent. Check the exporter's start time
     before suspecting the query.
 14. **Empty is not zero.** A counter with no observations has no series, and a ratio over
     an empty vector is empty - so a 0% error rate renders as "No data". Ratio panels wrap
     each counter in `or vector(0)`.
 15. **`just obs-verify` is the only check for third-party metric names.** The pytest
     metric-name test can only reach `django_*`/`celery_*`/`stockmarket_*`; node/redis/
     postgres come from Alloy's bundled exporters, which pytest cannot import.
     `infra/observability/verify_dashboards.py` queries every panel against the live
     Prometheus and found `pg_stat_database_rollback` (real name:
     `pg_stat_database_xact_rollback`). An EMPTY panel proves nothing on its own - idle
     and typo'd look identical, since `topk(histogram_quantile(...))` over an idle
     histogram is empty (topk drops NaNs) - so it asks which of the expression's metrics
     have NO series anywhere, and requires each absent name in `EXPECTED_MISSING`. Exact
     names, not panels: a misspelling is a different name, so it can never be silenced.
     Also: an alert rule on a misspelled metric is WORSE than a panel on one - it
     evaluates cleanly, reports `health=ok` and stays inactive forever, so the pytest
     name check now covers rule expressions too.
 16. **Never fire a test alert by stopping Redis** - it is the Celery broker. Stopping
     Alloy on `.208` fires the host-down rule (survivors < 3) at no cost to the app.
- **Config is tested in pytest** (`core/tests/test_observability_assets.py`) because all
  of it fails silently: a typo'd datasource uid is an empty panel, a mis-wired alert
  condition never evaluates, a renamed unit just stops shipping logs.

 17. **TRACES: enable the Alloy OTLP receiver on the APP HOST ONLY.** Tempo publishes
     `0.0.0.0:4317`/`:4318` on `.208` and `0.0.0.0` already covers `127.0.0.1`, so an Alloy
     receiver there cannot bind - and in Alloy a component that fails to start takes the
     WHOLE agent down, losing that host's logs and metrics too. Much bigger blast radius
     than "traces are missing". The receiver also binds loopback only: spans are
     attacker-controlled text rendered into a UI.
 18. **The Tempo image is DISTROLESS** - no shell, no wget/curl - so it gets NO docker
     healthcheck; a Loki-style probe cannot execute and pins the container at `unhealthy`
     while it serves fine. Likewise **Grafana's datasource health API does not work for
     Tempo** (`Method not implemented`); the Test button proxies `/api/echo`.
 19. **Validate infra config against the REAL binary, then mutation-check the validator.**
     `tempo -config.file=... -config.verify=true` (bare `-config.verify` prints usage and
     exits 2) and `alloy validate <file>`. Both caught nothing until deliberately broken -
     and one `alloy validate` run passed vacuously because a shell `cd` had silently left
     the wrong directory, so it validated an unmodified file. Verify the thing you think
     you are verifying.
 20. **This dev box's Docker daemon runs on another host and cannot see repo paths.**
     `docker run -v $PWD/x/y.yml:/...` silently creates a DIRECTORY named `y.yml`,
     clobbering the file - and cleaning it up needs root. Bake config into a throwaway
     image (`docker build -` with a tar on stdin) instead of bind-mounting.
 21. **Tempo has no size-based retention.** No `--storage.tsdb.retention.size` equivalent,
     so the disk guard is an INGESTION cap; its 15d `block_retention` is pinned by test to
     Prometheus' `retention.time` so a metric->trace click-through cannot land on a
     compacted-away trace. `max_block_duration: 5m` (vs 30m default) or a finished trace
     sits unqueryable in the WAL for half an hour, looking exactly like a broken pipeline.

 22. **Call `configure_tracing()` from EXPLICIT ENTRY POINTS, never `AppConfig.ready()`.**
     `wsgi.py` (gunicorn) and `celery.py` via `worker_process_init` (each prefork CHILD).
     `ready()` fires in every process calling `django.setup()` - each `manage.py` in a
     deploy, every pytest worker. Per-CHILD is load-bearing: `BatchSpanProcessor` runs a
     thread, threads do not survive `fork()`, so a parent-built provider leaves children
     queueing spans that never flush. `core/settings/test.py` FORCES the flag off so a
     developer's `.env` cannot make the suite depend on a collector.
 23. **`OTEL_TRACES_ENABLED` may live in the shared `.env` - the inverse of
     `PROMETHEUS_EXPORT_WORKER_PORTS`.** The difference is the entry points: Prometheus
     binds ports from `ready()` in EVERY process, tracing starts only where wsgi/celery
     call it. The `.env` task is tagged `observability` and NOTIFIES restart api+celery:
     systemd reads `EnvironmentFile` at unit START, so without that the file is correct
     while both services run on the old environment. (Before this, a `.env`-only Ansible
     change restarted nothing at all.)
 24. **`ParentBased` matters more than the sampling ratio.** Without it a sampled parent
     can have unsampled children, and the trace renders with holes that look like gaps in
     the SYSTEM rather than in the sampling.
 25. **Instrument Django BEFORE `get_wsgi_application()`.** `DjangoInstrumentor` INSERTS
     middleware into `settings.MIDDLEWARE`; `WSGIHandler.__init__` calls
     `load_middleware()` which reads that list once. Instrumenting after mutates a list
     nobody reads again - and it fails PARTIALLY so it looks fine: psycopg/redis/httpx
     spans still arrive, just with no request span above them, so every DB query becomes
     an orphan ROOT trace. Prod showed 5 traces all rooted at `SELECT`.
 26. **4xx/5xx log lines lose the trace id** for the same reason they once lost the
     request id: `BaseHandler.get_response` logs them AFTER the chain unwinds, when the
     span has ended. `RequestIDMiddleware` stamps `request.trace_id`/`span_id` while the
     span is live and `RequestIDFilter` falls back to them. Read the ids in the FILTER,
     never the formatter - they belong to the emitting context.
 27. **Tests and config cannot catch either of these.** Both were found only by
     generating real traffic in prod and reading the trace back. Deploy-and-verify is not
     optional for this phase.
 28. **OTel context does NOT cross a thread boundary, and it fails SILENTLY** - the work
     succeeds but reparents into its own ROOT trace, so the waterfall just stops showing
     structure. Both seams need `current_context()` + `attached(ctx)`:
     `stream_in_background`'s daemon thread and `chat_many`'s ThreadPoolExecutor.
 29. **Capture the context INSIDE the span you want as the parent.** Captured outside, the
     pool workers attach to the CALLER and every fan-out call becomes a SIBLING of
     `ollama.chat_many` rather than a child - the grouping span contains none of the work
     it exists to group. Found in PROD because the test asserted only the parent span's
     ATTRIBUTES and never that children nested under it. Assert structure, not just labels.
 30. **`tools.run_tool` must NEVER raise** - the docstring is the contract and the agent
     loops treat a tool error as data for the next turn. Its span records the error and
     still RETURNS the `{"error": ...}` observation.
 31. **Ollama returns token counts for free** (`prompt_eval_count`/`eval_count`) in the body
     `chat` already parses - now on every span, covering BOTH the web and Celery halves,
     which is exactly what the prometheus approach could not do.
 32. **THREE issue-#5 defects were tested, reviewed and wrong**, each invisible to the suite
     and obvious in one prod waterfall: instrumenting after `get_wsgi_application()` (orphan
     SELECT roots), 4xx/5xx lines with no `trace_id`, and the `chat_many` parenting above.
     Two looked PARTIALLY healthy, which is worse than a clean failure. Verify tracing
     against a real trace, never against tests alone.
 33. **Span-metric DIMENSIONS must be bounded.** They create a series per span name per
     dimension combination; `agent.run_id` would multiply every span name by every run
     ever executed. Only `llm.model` + `agent.kind`. Names arrive dots-to-underscores:
     query `llm_model`, never `llm.model`.
 34. **Exemplars need THREE switches** - `send_exemplars` (Tempo), `exemplar-storage`
     (Prometheus, else the write succeeds and only the id is dropped),
     `exemplarTraceIdDestinations` (Grafana). The label is camelCase **`traceID`**, NOT the
     `trace_id` our logs use; wrong name = Grafana still draws the dot, click does nothing.
 35. **PromQL regexes need TWO escaping layers.** `\.` is an invalid escape in a PromQL
     string literal -> Prometheus returns HTTP **400**, not an empty result. Panels need
     `ollama\\..*` in PromQL, i.e. `ollama\\\\..*` in the dashboard JSON. Too many
     backslashes matches a literal backslash and reads as idle. I broke this MYSELF while
     "fixing" it and `just obs-verify` was the only thing that caught it.
 36. **Alerting stays metric-based on purpose.** Span metrics would sit in NoData wherever
     tracing is off and would fire for trace-pipeline faults rather than app faults. Traces
     diagnose, metrics alert. A test pins the rule count at 12.
 37. **Per-step spans need TWO mechanisms.** `step_span()` wraps the loop body where the
     loop is in one place (chain/react/eval_opt/plan_execute); the rest already record
     started_at/completed_at, so `store.update_step` REPLAYS them as a span - one edit
     covering five modules, with the step's own duration rather than a wrapper's. `router`
     is exempt (no AgentStep rows at all). A structural test enforces the coverage.
 38. **Wrapper vs replay step spans are NOT equivalent.** A wrapper span is open during
     the step so LLM/tool calls nest inside it; a replayed span is built after the fact
     from stored timestamps, so the DURATION is right but nothing nests inside it - the
     step's LLM calls sit as siblings under `agent.run`. Seen in prod on an orchestrator
     run: agent.step 5622ms beside ollama.chat_many 5618ms, not containing it.
 39. **`_set_attributes` takes a POSITIONAL dict.** The keys contain dots, so `**kwargs`
     raises TypeError - which a bare `except Exception: pass` then swallows, leaving the
     function silently emitting nothing while looking healthy. Guards must WARN (once per
     process), not just pass. This was the 5th defect of this shape on issue #5, and the
     only one caused by my own defensive code.
 40. **`caplog` cannot see `core.*` records** - the `core` logger has `propagate: False`,
     so pytest's root handler never gets them. Assert on the logger object instead.

Related: [[project-state]], [[prod-infrastructure]]

**Issue #12 (2026-09-30):** a ninth dashboard, **Load Testing** (`sm-loadtest`), plus a "Load test" annotation on EVERY dashboard from `max by (testid) (k6_vus)`, so a k6 run does not read as an incident. `verify_dashboards.substitute` now also expands `$testid`, and every `k6_*` name is in `EXPECTED_MISSING`. See [[load-testing]].
