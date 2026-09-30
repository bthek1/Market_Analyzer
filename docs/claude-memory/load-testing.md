---
name: load-testing
description: "k6 load tests (issue #12): read-only browse journey, results remote-written to the .208 Prometheus, prod guard in the script; phases 1-3 built and verified locally, phases 4-5 need prod"
metadata:
  type: project
---

k6 load testing, [issue #12](https://github.com/bthek1/Market_Analyzer/issues/12). Doc:
`docs/project_docs/load-testing.md`. Scripts in `loadtest/k6/`, recipes `just lt*`.

**Status (2026-09-30):** phases 1-3 BUILT and verified against local dev. smoke, and a 13-min
`load` at 5 pages/s (5,212 requests, 0% failed, 20 token refreshes) ran green and were
remote-written to the REAL Prometheus on .208. `obs-verify` reported 0 unexplained panels out
of 101. NOT yet done: `just obs-deploy` (the dashboard is only in the repo until then);
phase 4 (prod baseline, off-hours, needs `ensure_loadtest_user` on prod); phase 5 (weekly CI
smoke). Hold phase 5 until the prod user and a `LOADTEST_PASSWORD` GitHub secret exist, or the
schedule fires red.

Non-obvious things learned while building it:
- **`k6 inspect` does NOT read the system environment; `k6 run` does.** Pass `-e`. The first
  `lt-inspect` exported LOADTEST_PROFILE and checked smoke five times with no error.
- dj-rest-auth with `JWT_AUTH_HTTPONLY=True` returns the refresh token ONLY in the
  `refresh-token` cookie (the body has `refresh: ""`). The refresh endpoint accepts it back
  in the body. Several VUs can share one refresh token only because `BLACKLIST_AFTER_ROTATION`
  is off.
- k6 v2 remote-write names: counters get `_total`, rates `_rate`, trends one series per
  configured stat (`_p95`). Trend stats are CUMULATIVE over the run, not windowed. Durations
  are in seconds. `k6_http_req_failed_rate` is useless aggregated, because each series has a
  fixed status and so reads 0 or 1. Failure % is computed from
  `k6_http_reqs_total{expected_response="false"}` instead.
- A threshold selector tolerates braces in the tag value: `http_req_duration{name:/api/companies/{id}/}` works.
- `handleSummary` replaces the default end-of-test summary. We print our own per-endpoint table
  rather than import jslib from the internet.
- Per-gunicorn-worker CPU/memory exists in prod as `process_*{job="django"}` (4 instances),
  so the dashboard shows real per-worker panels, not just host CPU.
- The dev box has only 4 cores. Don't run the pytest suite during a local load run, or the
  suite skews the numbers.

Related: [[observability]], [[env-config]], [[feedback-conventions]].
