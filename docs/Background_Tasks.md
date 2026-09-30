# Background Tasks & `sync_scheduled_tasks`

This document explains how periodic background work is defined, scheduled, and
run in the Market Analyzer, and how the `sync_scheduled_tasks` management
command keeps the database in sync with the code.

## Overview

Background work is handled by **Celery** (async task execution) and
**Celery Beat** (the periodic scheduler). The scheduler reads its schedule from
the database via `django-celery-beat`'s `DatabaseScheduler`, configured in
[backend/core/settings/base.py](../backend/core/settings/base.py):

```python
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
```

Because the schedule lives in the database (the `PeriodicTask` table), there has
to be a way to drive it from version-controlled code. That is the job of
`scheduled_tasks.py` (the source of truth) plus the `sync_scheduled_tasks`
command (the applier).

```
scheduled_tasks.py   ──►   sync_scheduled_tasks   ──►   PeriodicTask rows (DB)
(code, in git)             (management command)         (read by Celery Beat)
                                                              │
                                                              ▼
                                                        Celery worker runs
                                                        apps.companies.tasks.*
```

## The pieces

| Piece | Location | Role |
|---|---|---|
| `app = Celery("stockmarket")` | [backend/core/celery.py](../backend/core/celery.py) | Celery app; `autodiscover_tasks()` finds every `tasks.py` in installed apps |
| `SCHEDULED_TASKS` | [backend/apps/tasks/scheduled_tasks.py](../backend/apps/tasks/scheduled_tasks.py) | **Single source of truth** — the list of all periodic tasks |
| `sync_scheduled_tasks` | [backend/apps/tasks/management/commands/sync_scheduled_tasks.py](../backend/apps/tasks/management/commands/sync_scheduled_tasks.py) | Reconciles `PeriodicTask` rows with the list |
| Task functions | [backend/apps/companies/tasks.py](../backend/apps/companies/tasks.py) | The actual `@shared_task` work that runs |
| REST API | [backend/apps/tasks/views.py](../backend/apps/tasks/views.py), [urls.py](../backend/apps/tasks/urls.py) | List/toggle/trigger schedules, inspect results |

> The `tasks` app has **no models of its own**. It relies on `django-celery-beat`
> (`PeriodicTask`, `IntervalSchedule`, `CrontabSchedule`) and
> `django-celery-results` (`TaskResult`).

## `SCHEDULED_TASKS`: the source of truth

`scheduled_tasks.py` declares a list of dicts, one per periodic task. Each dict
maps to exactly one `PeriodicTask` row. Two schedule shapes are supported:

**Interval** — run every N units:

```python
{
    "name": "companies-tick-price-sync",        # unique identifier (also the DB row name)
    "task": "apps.companies.tasks.tick_price_sync",  # dotted path to the @shared_task
    "schedule_type": "interval",
    "every": 30,
    "period": "minutes",                        # seconds | minutes | hours | days
    "enabled": True,
}
```

**Crontab** — run at specific clock times:

```python
{
    "name": "companies-discover-new-symbols-weekly",
    "task": "apps.companies.tasks.discover_new_symbols",
    "schedule_type": "crontab",
    "minute": "0",
    "hour": "1",
    "day_of_week": "0",                         # Sunday 01:00
    # day_of_month / month_of_year default to "*"
    "enabled": True,
}
```

Crontab fields not specified default to `"*"`.

### To add or change a task

1. Edit the `SCHEDULED_TASKS` list in `scheduled_tasks.py`.
2. Run `python manage.py sync_scheduled_tasks`.

Never hand-edit `PeriodicTask` rows in the DB or admin for managed tasks — the
next sync will overwrite (or prune) them.

## The `sync_scheduled_tasks` command

The command reconciles the database to match the code. For each spec it does an
`update_or_create` keyed on `name`; afterwards it prunes any `PeriodicTask` rows
whose name is not in `SCHEDULED_TASKS`.

```bash
python manage.py sync_scheduled_tasks            # apply changes
python manage.py sync_scheduled_tasks --dry-run  # preview only, writes nothing
```

What it does, step by step:

1. **Resolve the schedule.** For an `interval` spec it `get_or_create`s an
   `IntervalSchedule(every, period)`; for a `crontab` spec it `get_or_create`s a
   `CrontabSchedule(minute, hour, day_of_week, day_of_month, month_of_year)`.
   Schedule objects are shared/reused across tasks with the same timing.
2. **Upsert the task.** `PeriodicTask.objects.update_or_create(name=...)` sets
   `task`, `enabled`, and the resolved `interval`/`crontab` (one is set, the
   other `None`). Prints `created:` or `updated:`.
3. **Prune.** Any `PeriodicTask` whose name is not in the current list is
   deleted (prints `deleted:`). This is what makes the code authoritative — a
   removed entry in `scheduled_tasks.py` disappears from the DB on next sync.

`--dry-run` prints `[dry-run] would create/update/delete: <name>` without
touching the database — useful before applying changes in production.

This command runs automatically as part of deploys (it is safe and idempotent),
so the deployed schedule always reflects `main`.

## Structure of the background tasks

Most of the work lives in [backend/apps/companies/tasks.py](../backend/apps/companies/tasks.py)
as Celery `@shared_task` functions, falling into the three groups below; the knowledge graph
adds its own maintenance sweeps in [backend/apps/knowledge_graph/tasks.py](../backend/apps/knowledge_graph/tasks.py)
(group 4). `autodiscover_tasks()` finds every `tasks.py`, so a NEW task is only registered after
the Celery worker is **restarted** (the worker reads its task registry once at startup).

### 1. Bootstrap flow (onboarding new symbols)

| Task | Schedule | What it does |
|---|---|---|
| `discover_new_symbols` | Sun 01:00 (crontab) | Scrapes index lists (S&P 500, NASDAQ-100), creates un-bootstrapped `Company` stubs |
| `bootstrap_tick` | every 20 min | Fully ingests the next 5 un-bootstrapped companies (price/snapshot/financials/etc.); a no-op once the queue is drained |

### 2. Backfill (one-shot maintenance)

| Task | Schedule | What it does |
|---|---|---|
| `backfill_snapshot_fields_task` | Sun 01:30 (crontab) | Backfills missing snapshot fields; becomes a no-op once complete |

### 3. Rolling tick sync (steady-state freshness)

These are the workhorses. Each tick processes the **`batch_size` most-stale**
bootstrapped companies for one data type, then records the sync time. Because
each tick handles a fixed-size batch, **load stays constant regardless of how
many companies exist** — the full-refresh cycle time simply lengthens as the
database grows.

| Task | Schedule | Approx. cycle (~500 companies) |
|---|---|---|
| `tick_price_sync` | every 30 min | daily |
| `tick_snapshot_sync` | every 30 min | daily |
| `tick_options_sync` | every 30 min (weekday guard inside) | daily |
| `tick_profile_sync` | every 3 h | weekly |
| `tick_earnings_dates_sync` | every 3 h | weekly |
| `tick_dividend_sync` | every 3 h | weekly |
| `tick_financial_sync` | every 12 h | monthly |
| `tick_institutional_holders_sync` | every 48 h | quarterly |
| `tick_short_interest_sync` | every 48 h | bi-monthly settlement |
| `tick_summary_generation` | every 6 h, batch 5 | LLM summaries (expensive, small batch) |

### 4. Knowledge graph maintenance (steady-state hygiene)

Defined in [backend/apps/knowledge_graph/tasks.py](../backend/apps/knowledge_graph/tasks.py).
The expansion-time triggers only re-check nodes an expansion just touched, so these Beat
sweeps keep an idle graph tidy. Both are idempotent and self-guard to a no-op when nothing
is due.

| Task | Schedule | What it does |
|---|---|---|
| `sweep_rerank_candidates` | every 5 min | Queues an LLM `rerank_node_task` for every node over `KG_RERANK_TRIGGER` (30) edges; each keeps the `KG_RERANK_TARGET` (15) strongest/most-correct edges |
| `sweep_transitive_edges` | every 15 min | Transitive reduction — drops an `A -rel-> C` edge implied by a longer `A -> B -> C` same-relation path (pure DB work) |

The graph also runs **on-demand** (not Beat) tasks: `expand_concept_task` (per-node Expand /
1st-degree), `crawl_hub_task` (auto-expand's top-5 ring crawl, and the 2nd/3rd-degree
expand buttons with `rings = degree - 1`). The ring crawl expands its node then recurses
outward one ring at a time; its INTERMEDIATE rings follow `all_neighbor_ids` (traversing
through already-expanded neighbours) and only the final ring restricts to
`unexpanded_neighbor_ids`, so a deep crawl still reaches the unexpanded frontier beyond an
already-expanded inner ring (the `rings` budget bounds it and `expand_concept` is idempotent,
so revisits around cycles are cheap no-ops). Both carry a cancel "epoch" so
`POST /api/knowledge/expansion/clear/` can purge + cancel a runaway crawl. **Adding a new
task here (e.g. `crawl_hub_task`) requires a Celery worker restart** — the worker registers
its task types only at startup.

### How "most-stale" is chosen

Staleness is tracked per (company, data type) in `CompanySyncRecord`. The shared
helper `_stale_symbols(sync_type, batch_size=10)` returns the bootstrapped
symbols with the oldest `last_synced_at` for that `sync_type`, treating "never
synced" as the Unix epoch so new companies sort first:

```python
def _stale_symbols(sync_type, batch_size=10):
    latest_sync = CompanySyncRecord.objects.filter(
        company=OuterRef("pk"), sync_type=sync_type
    ).values("last_synced_at")[:1]
    return list(
        Company.objects.filter(is_bootstrapped=True)
        .annotate(last_sync=Coalesce(Subquery(latest_sync), Value(epoch)))
        .order_by("last_sync")[:batch_size]
        .values_list("symbol", flat=True)
    )
```

A typical tick task: pick the stale batch → loop and sync each symbol with
per-symbol error isolation (a failure is logged and counted, never aborts the
batch) → `_record_sync(symbols, sync_type)` to stamp `last_synced_at = now` →
return a small result dict (`{"ok": .., "failed": .., ...}`). The default
`_BATCH_SIZE` is `10` (summary generation uses `5`).

## Inspecting and controlling tasks at runtime

The `tasks` app exposes a small REST API (all `IsAuthenticated`), surfaced in the
frontend's Tasks/Schedules pages:

| Endpoint | View | Purpose |
|---|---|---|
| `GET /api/tasks/schedules/` | `PeriodicTaskListView` | List all periodic tasks (with interval/crontab) |
| `PATCH /api/tasks/schedules/<pk>/` | `PeriodicTaskToggleView` | Enable/disable a task (`{"enabled": bool}`) |
| `POST /api/tasks/schedules/<pk>/trigger/` | `PeriodicTaskTriggerView` | Fire a task immediately; returns `{"task_id"}` |
| `GET /api/tasks/results/` | `TaskResultListView` | Recent run results (optional `?status=`) |
| `GET /api/tasks/results/<task_id>/` | `TaskResultDetailView` | One run's result |

Toggling `enabled` via the API is fine for ad-hoc pausing, but note that
`sync_scheduled_tasks` resets `enabled` to the value in `scheduled_tasks.py`
on the next run — make a setting permanent by editing the code.

## Running the stack locally

```bash
just db-up        # PostgreSQL + Redis (broker/result backend)
just be-celery    # Celery worker (executes tasks)
# Celery Beat (the scheduler) runs as part of `just dev` / the prod systemd units
```

To trigger a single task without the scheduler, use the API `trigger` endpoint
or call it from `just be-shell`:

```python
from apps.companies.tasks import tick_price_sync
tick_price_sync.delay()   # enqueue
tick_price_sync()         # run inline (synchronous)
```
