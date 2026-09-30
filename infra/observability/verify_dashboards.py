#!/usr/bin/env python3
"""Query every provisioned dashboard panel against the live Prometheus.

A metric-name typo, a renamed exporter label or a ratio whose numerator series has
never existed all fail the same silent way: the panel renders, the query returns
nothing, and the dashboard reads as "No data" - which looks identical to "the thing
being measured is idle". Nothing errors, so it is only found by asking Prometheus.

`backend/core/tests/test_observability_assets.py` pins what CAN be checked offline
(uids, alert conditions, panel layout, and our OWN metric names against the live
prometheus_client registry). It deliberately cannot cover the bundled exporters -
node/redis/postgres are not importable from the test suite - so the names in
`pg_stat_database_*`, `redis_*` and `node_*` panels are exactly what this script is
for. It found `pg_stat_database_rollback`, which does not exist (it is
`pg_stat_database_xact_rollback`).

Needs the LAN stack, so it is not a CI check:

    just obs-verify                     # against 192.168.2.208
    just obs-verify --prometheus URL    # somewhere else

An empty result is NOT judged on its own, because an idle system and a misspelled
metric look identical from the outside: `topk(5, histogram_quantile(...))` over a
histogram with no increase in the window is empty (topk drops the NaNs), exactly like a
name that does not exist. So on empty or NaN the script asks which of the expression's
metrics have **no series at all** - that is the part idleness cannot explain. Exit status
is 0 when every absent name is declared in EXPECTED_MISSING below.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DASHBOARDS = Path(__file__).resolve().parent / "grafana" / "dashboards"
DEFAULT_PROMETHEUS = "http://192.168.2.208:9090"

# Grafana expands these server-side; a fixed window is close enough to prove a series
# exists, which is all this script claims to check.
INTERVAL_SUBSTITUTIONS = {
    "$__rate_interval": "5m",
    "$__interval": "1m",
    "$__range": "1h",
}

# Metric names that legitimately have NO series yet, and why. A metric whose absence
# depends on a state that has simply not happened is not a defect - but it must be
# declared here, or a clean run stops meaning anything.
#
# Declaring exact NAMES rather than panels or expressions is what keeps this honest: a
# misspelling produces a different name, so it cannot be silenced by an entry here.
LABELLED_AFTER_MIDDLEWARE = (
    "labelled by django-prometheus' After middleware, which creates a series on first "
    "observation - so nothing exists until the first request after a worker restart"
)
ABSENT_OUTSIDE_A_LOAD_RUN = "absent outside a load run (k6 pushes it only while one is live)"
EXPECTED_MISSING = {
    "stockmarket_agent_runs": "labelled gauge: no series until the first AgentRun row exists",
    "stockmarket_agent_runs_stuck": "labelled gauge: no series while no run is stuck",
    "celery_task_failed_total": "a Counter with no observations yet - no task has failed",
    "celery_task_retried_total": "a Counter with no observations yet - no task has retried",
    "django_http_requests_total_by_method_total": LABELLED_AFTER_MIDDLEWARE,
    "django_http_responses_total_by_status_total": LABELLED_AFTER_MIDDLEWARE,
    "django_http_requests_latency_seconds_by_view_method_bucket": LABELLED_AFTER_MIDDLEWARE,
    # The Load Testing dashboard (issue #12). k6 remote-writes these only while a run is
    # live, so outside one they go stale and have no series - which is the normal state.
    "k6_vus": ABSENT_OUTSIDE_A_LOAD_RUN,
    "k6_vus_max": ABSENT_OUTSIDE_A_LOAD_RUN,
    "k6_http_reqs_total": ABSENT_OUTSIDE_A_LOAD_RUN,
    "k6_http_req_duration_p95": ABSENT_OUTSIDE_A_LOAD_RUN,
    "k6_http_req_duration_p99": ABSENT_OUTSIDE_A_LOAD_RUN,
    "k6_checks_rate": ABSENT_OUTSIDE_A_LOAD_RUN,
    "k6_data_received_total": ABSENT_OUTSIDE_A_LOAD_RUN,
    "k6_data_sent_total": ABSENT_OUTSIDE_A_LOAD_RUN,
    "k6_dropped_iterations_total": (
        "absent outside a load run, and even during one until k6 runs out of VUs"
    ),
    "k6_auth_refreshes_total": (
        "absent outside a load run, and during one until a token is refreshed (10 min)"
    ),
}

# PromQL words that look like metric names to a regex. Most functions are excluded
# structurally (a name followed by "(" is a call, never a metric) and label names by
# being stripped with their `{...}` / `by (...)` context, which leaves the aggregation
# operators and bare modifiers to list by hand.
PROMQL_KEYWORDS = frozenset(
    {
        # Aggregation operators take their argument after a `by (...)` clause, so the
        # "followed by (" rule does not catch them.
        "avg",
        "bottomk",
        "count",
        "group",
        "max",
        "min",
        "quantile",
        "stddev",
        "stdvar",
        "sum",
        "topk",
        "and",
        "bool",
        "by",
        "group_left",
        "group_right",
        "ignoring",
        "inf",
        "nan",
        "le",
        "offset",
        "on",
        "or",
        "unless",
        "without",
    }
)


def substitute(expr):
    for token, value in INTERVAL_SUBSTITUTIONS.items():
        expr = expr.replace(token, value)
    # The dashboards template the host selector (and the load-test dashboard its testid
    # run picker); matching every value is what a panel with "All" selected does anyway.
    return re.sub(r"\$\{?(?:host|testid)(:[a-z]+)?\}?", ".*", expr)


def panel_targets(path):
    """(panel title, expr) for every target, including panels nested in rows."""
    board = json.loads(path.read_text())
    out = []

    def walk(panels):
        for panel in panels:
            walk(panel.get("panels") or [])
            for target in panel.get("targets") or []:
                expr = target.get("expr")
                if expr:
                    out.append((panel.get("title") or "(untitled)", expr))

    walk(board.get("panels") or [])
    return out


def query(prometheus, expr):
    """(status, detail) where status is one of ok/empty/nan/error."""
    url = f"{prometheus}/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            payload = json.load(response)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return "error", str(exc)
    if payload.get("status") != "success":
        return "error", payload.get("error", "unknown Prometheus error")

    result = payload["data"]["result"]
    if not result:
        return "empty", "no series"
    # A quantile over a histogram with no recent increase is NaN, not empty. Reported
    # separately because it means "the series exists but is idle", not "wrong name".
    values = [series.get("value", [None, None])[1] for series in result]
    if values and all(value == "NaN" for value in values):
        return "nan", "all NaN (idle histogram)"
    return "ok", f"{len(result)} series"


def metric_names(expr):
    """The metric names an expression references.

    Label names are removed by deleting the two places they appear - `{...}` matchers and
    `by (...)` / `without (...)` groupings - and a name followed by "(" is a function
    call, never a metric. What survives is metric names plus the bare operators, which
    PROMQL_KEYWORDS lists.
    """
    stripped = re.sub(r"\{[^}]*\}", " ", expr)
    stripped = re.sub(r"\b(?:by|without)\s*\([^)]*\)", " ", stripped)
    # Case matters: node_exporter emits CamelCase (node_memory_MemAvailable_bytes), and a
    # lowercase-only pattern skipped those names entirely - which silently "explained"
    # every empty panel on the host dashboard.
    candidates = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b(?!\s*[(=!])", stripped)
    return {name for name in candidates if name not in PROMQL_KEYWORDS}


def missing_metrics(prometheus, expr):
    """Which of the expression's metrics have no series at all.

    This is the question that actually separates a typo from an idle system, and it is
    why an empty result is not judged on its own: `topk(5, histogram_quantile(...))` over
    an idle histogram is empty, not NaN, because topk drops the NaN samples - identical
    in shape to a misspelled metric name. Asking about each name individually tells them
    apart.
    """
    absent = []
    for name in sorted(metric_names(expr)):
        status, _detail = query(prometheus, f"count({name})")
        if status in ("empty", "nan"):
            absent.append(name)
    return absent


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prometheus", default=DEFAULT_PROMETHEUS)
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print panels that are not OK.",
    )
    args = parser.parse_args(argv)

    total = 0
    problems = []
    accepted = []
    for path in sorted(DASHBOARDS.glob("*.json")):
        print(f"\n{path.name}")
        for title, expr in panel_targets(path):
            total += 1
            status, detail = query(args.prometheus, substitute(expr))
            if status == "ok":
                if not args.quiet:
                    print(f"  ok      {title} ({detail})")
                continue
            if status == "error":
                problems.append((path.name, title, expr, detail))
                print(f"  ERROR   {title}: {detail}\n          {expr}")
                continue

            # Empty or NaN on its own says nothing: an idle system and a misspelled
            # metric look the same from here. So ask which of the expression's metrics
            # have no series at all - that is the part that cannot be explained away.
            absent = missing_metrics(args.prometheus, substitute(expr))
            undeclared = [name for name in absent if name not in EXPECTED_MISSING]
            if undeclared:
                detail = f"no series for {', '.join(undeclared)}"
                problems.append((path.name, title, expr, detail))
                print(f"  MISSING {title}: {detail}\n          {expr}")
            elif absent:
                reasons = "; ".join(f"{name}: {EXPECTED_MISSING[name]}" for name in absent)
                accepted.append((path.name, title, reasons))
                print(f"  empty   {title} - expected: {reasons}")
            else:
                accepted.append((path.name, title, "every metric exists; nothing to report"))
                print(f"  idle    {title} - every metric exists, the window is quiet")

    print(
        f"\n{total} panel targets | {len(problems)} unexplained | {len(accepted)} idle-or-expected"
    )
    if problems:
        print("\nUnexplained panels (a typo, a renamed label, or a genuinely dead metric):")
        for name, title, expr, detail in problems:
            print(f"  {name} | {title} | {detail}\n    {expr}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
