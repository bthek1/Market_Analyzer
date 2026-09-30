# Load testing — k6 into the existing Grafana

[Issue #12](https://github.com/bthek1/Market_Analyzer/issues/12). k6 scripts in `loadtest/k6/`
send **read-only** traffic at the real API. Their metrics go to the Prometheus on `.208`,
so a run shows up on the **Load Testing** dashboard (uid `sm-loadtest`) next to the
Django, Postgres, Redis and host metrics for the same time window.

The observability stack explains a slow request after it happens. This measures **when**
the app gets slow: the request rate at which the four gunicorn workers saturate, which
resource gives out first, and whether a change made things slower.

## Running it

```bash
just lt-install                 # pinned static k6 binary into ~/.local/bin (no sudo, no Docker)
just lt-user                    # create/refresh the non-staff load-test user
just lt-smoke                   # 1 VU, 30 s, against local `just dev`
just lt load local              # just lt PROFILE TARGET
just lt-inspect                 # parse every script x profile, send nothing
LOADTEST_ALLOW_PROD=1 just lt load prod   # prod: see "Against prod" below
```

Configuration is the `LOADTEST_*` keys in the repo-root `.env` (see `.env.example`):

| Key | Default | Meaning |
|---|---|---|
| `LOADTEST_EMAIL` / `LOADTEST_PASSWORD` | `loadtest@stockmarket.local` / — | The dedicated account. The local part must start with `loadtest`. |
| `LOADTEST_RATE` | `5` | Expected peak, in **page views per second**. Every profile is shaped from it. |
| `LOADTEST_ALLOW_PROD` | unset | Must be `1` to target prod. Set it for one command, never in `.env`. |
| `LOADTEST_BASE_URL` | per target | Override the target URL. A prod host is still refused without the flag. |
| `LOADTEST_MAX_VUS` | `200` | Ceiling for the arrival-rate executors. |
| `LOADTEST_TOKEN_REFRESH_S` | `600` | Refresh the access token after this long. Lower it to exercise the refresh path in a short run. |
| `LOADTEST_OUTPUT` | `prometheus` | `none` skips the remote write, for example when off the LAN. |

Each run prints a per-endpoint table (count, p50/p95/p99/max, threshold pass) and writes the
full k6 summary to `loadtest/results/<testid>.json` (gitignored), so runs can be diffed.

## The workload

`scenarios/browse.js` is an "analyst browsing" journey. **One iteration is one page view**,
chosen by weight, and it makes the API calls that page makes:

| Page | Weight | Requests |
|---|---|---|
| companies list | 20 | `companies/?page=&ordering=` |
| company search | 10 | `companies/?search=` |
| company overview | 25 | `companies/{id}/`, `/prices/?ordering=-date`, `/snapshots/` |
| financials tab | 10 | `/financials/?period=annual` |
| dividends tab | 5 | `/dividends/` |
| sectors | 10 | `companies/sectors/` |
| market map | 8 | `companies/market-hierarchy/?metric=` |
| sync freshness | 5 | `companies/sync-freshness/` |
| account | 7 | `accounts/me/` |

The weights are a guess at an analyst's session, not a measurement: there is no log of
real read traffic to derive them from. Company ids come from the list endpoint in
`setup()` (bootstrapped companies only, since a stub would measure an empty query), so the
same script works on dev and prod. Smoke visits the pages in turn instead of drawing, so
its ~15 iterations always touch every endpoint.

**Auth.** `setup()` logs in once (`POST /api/auth/login/`) and hands the tokens to every
VU. dj-rest-auth runs with `JWT_AUTH_HTTPONLY=True`, so the access token comes back in the
body but the refresh token **only** in the HttpOnly `refresh-token` cookie. It is read from
there and sent back in the refresh body. Access tokens last 15 minutes, so each VU
refreshes its own after 10. Without that, a soak run becomes a flood of 401s from minute
15 on. VUs can share one refresh token because `BLACKLIST_AFTER_ROTATION` is off. If
that changes, a failed refresh falls back to a fresh login. The `auth_refreshes` counter
(the **Token refreshes** tile) proves the path ran.

## Profiles

`LOADTEST_PROFILE` picks one. The endpoints are defined once; a profile is only a k6
scenario plus its thresholds (`lib/profiles.js`).

| Profile | Shape (R = `LOADTEST_RATE`) | What it answers |
|---|---|---|
| `smoke` | 1 VU, 30 s, 1–3 s think time | Do the scripts work? Measures nothing. |
| `load` | ramp to R over 2 m, hold 10 m | Latency at the expected peak. |
| `stress` | +R every 3 m up to 10R | Where is the knee? Expected to abort on a threshold. |
| `spike` | 1 → 5R in 10 s, hold 1 m, back to 1 for 3 m | Does it recover, and how fast does the tail drain? |
| `soak` | R/2 for 70 m | Memory growth in the workers, connection leaks, token expiry. |

Everything except smoke uses **`ramping-arrival-rate`**, an open model. Iterations start
on schedule whether or not the server keeps up. A closed model (N VUs looping) slows
its own arrival rate as the server slows, which hides exactly the saturation being
looked for. When an open model hits its ceiling, it shows up as **dropped iterations**:
k6 ran out of VUs to start iterations on time because the server is holding them.

**Thresholds** (all `abortOnFail`, so a run against prod stops itself):
`http_req_failed < 1%`, `checks > 99%`, and a p95 budget per endpoint via its `name` tag,
grouped by kind:

| Kind | p95 budget |
|---|---|
| list | 1000 ms |
| detail | 500 ms |
| aggregate (`market-hierarchy`, `sync-freshness`) | 2000 ms |
| auth (login, refresh) | 2000 ms |

These are **placeholders** until the prod baseline below replaces them with baseline p95
plus headroom.

## Design decisions

- **Self-hosted results, not Grafana Cloud k6.** Prometheus on `.208` already accepts
  remote write (Alloy depends on it), so there is no new service, account or key.
- **The k6 binary, not Docker.** The Docker daemon on the dev box runs on another host
  and cannot see repo paths. `docker run -v` would quietly mount an empty directory
  where the script should be.
- **`k6 inspect` does not read the system environment**, unlike `k6 run`. Pass variables
  with `-e`. An exported `LOADTEST_PROFILE` is ignored without any error, which is how
  the first version of `lt-inspect` came to check the smoke profile five times.
- **Read-only traffic, against the real API behind nginx.**
- **Cardinality.** k6 tags every request with its full `url` by default, and each tag
  becomes a Prometheus label, so `/api/companies/123/prices/` would be one series per
  company. The system tags are an explicit allow-list without `url`, `vu` and `iter`. Every
  request carries a templated `name` tag, which is also its path template in
  `lib/endpoints.js`, so the two cannot drift. Check names are fixed strings for the same
  reason.
- **Trend stats as gauges** (`K6_PROMETHEUS_RW_TREND_STATS=p(95),p(99),avg,max`), not
  native histograms. Native histograms would need another Prometheus feature flag and a
  restart, for precision this baseline does not need. The catch is that k6 computes these
  over the whole run so far, so they lag. The windowed Django histogram on the same
  dashboard is where to read the knee.
- **Annotations come from `k6_vus`**, via a Prometheus annotation on every dashboard. The
  generator needs no Grafana credential, and an aborted run is still marked.
- **The prod guard is in the script, not just the justfile.** `lib/config.js` throws in
  the init context when the target is prod, or when the base URL is a prod host, without
  `LOADTEST_ALLOW_PROD=1`. That also covers `k6 inspect` and a hand-typed `k6 run`.

## Non-goals

- **`/api/llm/*`.** These are bound by one RTX 3060 and `OLLAMA_NUM_PARALLEL`, and load
  would push the classifier out of VRAM.
- **The browser agent.** It has its own semaphore (429) and a 10/hour throttle, so a load
  test would only measure those.
- **yfinance sync/ingest** (`/sync/`, `/yf/`). These call Yahoo, which rate-limits us.
- **`/api/health/` inside the iteration.** Each call is a Celery broadcast ping, a `git
  describe` and an Ollama probe. It is called once, in `setup()`, as a precondition
  (`db` and `redis` must be true; Celery and Ollama are not on the read path).
- **Writes and knowledge-graph expansion.** They start Celery fan-out and LLM calls.
- **Running on every push.** A load test against prod on every push would itself be an
  incident.

`backend/core/tests/test_loadtest_contract.py` enforces these: every path resolves in
Django, no non-goal path appears, `/api/health/` lives only in `lib/preflight.js` and is
only called from `setup()`, every HTTP call is named, every threshold aborts, the load
profiles are open-model, and every profile refuses prod without the flag. The k6-backed
half skips where k6 is not installed.

## Against prod

Run from the LAN (the dev box or the `gh-runner` LXC, VMID 111), **never on the app
host**: the generator would compete with gunicorn for the same 2 CPUs. Run off-hours, and
set `LOADTEST_ALLOW_PROD=1` for that one command. The load-test user has to exist on prod
first:

```bash
ssh root@stockmarket "cd /home/app/stock_market/backend && LOADTEST_PASSWORD=... \
  /home/app/.local/bin/uv run python manage.py ensure_loadtest_user"
```

Known limits: 4 gunicorn workers on a 2 CPU / 4 GB app container, and PostgreSQL on a
2 CPU / 2 GB container.

## Baseline

Not measured yet (issue #12 phase 4). It will record RPS and p95/p99 per `name` at the
knee, which resource saturated first and how that was established (dashboard panel and
trace), and the thresholds derived from it.
