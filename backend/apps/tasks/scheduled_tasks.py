from typing import Any

# Single source of truth for all periodic tasks.
# Each dict maps to one PeriodicTask row managed by the sync_scheduled_tasks command.
#
# schedule_type "interval": requires every (int) + period ("seconds"|"minutes"|"hours"|"days")
# schedule_type "crontab":  minute/hour/day_of_week/day_of_month/month_of_year (default "*")
#
# To add or change a task: edit this list, then run:
#   python manage.py sync_scheduled_tasks

SCHEDULED_TASKS: list[dict[str, Any]] = [
    # ------------------------------------------------------------------
    # Bootstrap flow: discover new symbols weekly, drain bootstrap queue
    # every 20 min. Becomes a no-op once all symbols are bootstrapped.
    # ------------------------------------------------------------------
    {
        "name": "companies-discover-new-symbols-weekly",
        "task": "apps.companies.tasks.discover_new_symbols",
        "schedule_type": "crontab",
        "minute": "0",
        "hour": "1",
        "day_of_week": "0",  # Sunday 01:00
        "enabled": True,
    },
    {
        "name": "companies-bootstrap-tick",
        "task": "apps.companies.tasks.bootstrap_tick",
        "schedule_type": "interval",
        "every": 20,
        "period": "minutes",
        "enabled": True,
    },
    # ------------------------------------------------------------------
    # Backfill: one-shot, runs weekly as a no-op once complete.
    # ------------------------------------------------------------------
    {
        "name": "companies-backfill-snapshot-fields-weekly",
        "task": "apps.companies.tasks.backfill_snapshot_fields_task",
        "schedule_type": "crontab",
        "minute": "30",
        "hour": "1",
        "day_of_week": "0",  # Sunday 01:30
        "enabled": True,
    },
    # ------------------------------------------------------------------
    # Rolling tick sync: each tick processes the batch_size most-stale
    # bootstrapped companies. Load is constant regardless of company count;
    # cycle time scales naturally as the database grows.
    # ------------------------------------------------------------------
    # Price sync -- every 30 min (daily cycle for ~500 companies)
    {
        "name": "companies-tick-price-sync",
        "task": "apps.companies.tasks.tick_price_sync",
        "schedule_type": "interval",
        "every": 30,
        "period": "minutes",
        "enabled": True,
    },
    # Snapshot sync -- every 30 min
    {
        "name": "companies-tick-snapshot-sync",
        "task": "apps.companies.tasks.tick_snapshot_sync",
        "schedule_type": "interval",
        "every": 30,
        "period": "minutes",
        "enabled": True,
    },
    # Options sync -- every 30 min (weekday guard inside the task)
    {
        "name": "companies-tick-options-sync",
        "task": "apps.companies.tasks.tick_options_sync",
        "schedule_type": "interval",
        "every": 30,
        "period": "minutes",
        "enabled": True,
    },
    # Profile sync -- every 1 hour
    {
        "name": "companies-tick-profile-sync",
        "task": "apps.companies.tasks.tick_profile_sync",
        "schedule_type": "interval",
        "every": 1,
        "period": "hours",
        "enabled": True,
    },
    # Earnings dates sync -- every 1 hour
    {
        "name": "companies-tick-earnings-dates-sync",
        "task": "apps.companies.tasks.tick_earnings_dates_sync",
        "schedule_type": "interval",
        "every": 1,
        "period": "hours",
        "enabled": True,
    },
    # Dividend sync -- every 1 hour
    {
        "name": "companies-tick-dividend-sync",
        "task": "apps.companies.tasks.tick_dividend_sync",
        "schedule_type": "interval",
        "every": 1,
        "period": "hours",
        "enabled": True,
    },
    # Financial sync -- every 4 hours
    {
        "name": "companies-tick-financial-sync",
        "task": "apps.companies.tasks.tick_financial_sync",
        "schedule_type": "interval",
        "every": 4,
        "period": "hours",
        "enabled": True,
    },
    # Institutional holders sync -- every 12 hours
    {
        "name": "companies-tick-institutional-holders-sync",
        "task": "apps.companies.tasks.tick_institutional_holders_sync",
        "schedule_type": "interval",
        "every": 12,
        "period": "hours",
        "enabled": True,
    },
    # Short interest sync -- every 12 hours
    {
        "name": "companies-tick-short-interest-sync",
        "task": "apps.companies.tasks.tick_short_interest_sync",
        "schedule_type": "interval",
        "every": 12,
        "period": "hours",
        "enabled": True,
    },
    # Summary generation -- every 2 hours, batch 5 (LLM generation is expensive)
    {
        "name": "companies-tick-summary-generation",
        "task": "apps.companies.tasks.tick_summary_generation",
        "schedule_type": "interval",
        "every": 2,
        "period": "hours",
        "enabled": True,
    },
    # ------------------------------------------------------------------
    # Knowledge graph: sweep every 5 min for hub nodes over the rerank
    # trigger and queue an LLM rerank-and-prune for each. Decouples hub
    # clean-up from expansion so an idle graph still gets tidied; a no-op
    # when nothing is over the trigger.
    # ------------------------------------------------------------------
    {
        "name": "knowledge-sweep-rerank-candidates",
        "task": "apps.knowledge_graph.tasks.sweep_rerank_candidates",
        "schedule_type": "interval",
        "every": 5,
        "period": "minutes",
        "enabled": True,
    },
    # ------------------------------------------------------------------
    # Knowledge graph: transitive reduction of the hierarchy every 15 min.
    # Drops edges implied by a longer same-relation path (A->C when A->B->C
    # exists). Pure DB work, idempotent, a no-op when already reduced.
    # ------------------------------------------------------------------
    {
        "name": "knowledge-sweep-transitive-edges",
        "task": "apps.knowledge_graph.tasks.sweep_transitive_edges",
        "schedule_type": "interval",
        "every": 15,
        "period": "minutes",
        "enabled": True,
    },
    # ------------------------------------------------------------------
    # Browser agent: drop step screenshots past the retention window (they
    # are captures of live web pages, not durable app data). Daily, no-op
    # when nothing is due or the feature was never used.
    # ------------------------------------------------------------------
    {
        "name": "llm-sweep-browser-screenshots",
        "task": "apps.llm_analysis.tasks.sweep_browser_screenshots",
        "schedule_type": "crontab",
        "minute": "15",
        "hour": "3",
        "enabled": True,
    },
]
