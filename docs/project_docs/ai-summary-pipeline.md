# AI Company Summary - How It Works Today

Reference documentation for the `CompanySummary` generation path **as of 2026-09-16**, captured
before the rewrite tracked in [issue #1](https://github.com/bthek1/Market_Analyzer/issues/1).
This is the "before" half of that issue's Phase 1.

> **Superseded in part by [issue #3](https://github.com/bthek1/Market_Analyzer/issues/3).** Issue #1's
> Phases 3-5 (the `equity_report` pipeline) were dropped; #3 fixed the inputs and the verdict
> instead, keeping the single call. The audit below is the **"before" record** and is left as
> written - see *What issue #3 changed* at the end for the current shape of the path.

## The call path

```
POST /api/companies/{symbol}/summaries/generate/
  -> views.CompanySummaryGenerateView          (404s unknown symbol, then fire-and-forget)
     -> current_app.send_task("apps.companies.tasks.generate_summary_single", [SYMBOL])
        -> 202 {"task_id", "status": "queued"}          <-- returns immediately, no result link

Celery worker
  -> tasks.generate_summary_single(symbol)     (bind=True, max_retries=2, retry_delay=60s;
     |                                          retries ONLY on OllamaServiceError)
     -> services.generate_company_summary(symbol)       services.py:1195
        |
        |-- Company.objects.select_related("sector","industry").get(symbol=symbol)
        |     (raises Company.DoesNotExist - NOT caught by the task)
        |
        |-- _assemble_company_data(company)   -> dict   services.py:1005
        |     ~8 queries, all "latest row" lookups; every value pre-FORMATTED to a string
        |
        |-- _build_prompt_text(data)          -> str    services.py:1126
        |     flattens the dict into a "[Section]\n  key: value" plain-text block
        |
        |-- ollama_chat([system=_SUMMARY_SYSTEM_PROMPT, user=prompt_text])
        |     ONE blocking call, OLLAMA_MAIN_MODEL, no temperature, no format schema
        |
        |-- _parse_verdict(response)          -> str    services.py:1180
        |     regex /VERDICT:\s*(BUY|HOLD|SELL|INSUFFICIENT_DATA)/i
        |     no match -> logs a warning, returns insufficient_data
        |
        `-- CompanySummary.objects.create(company, model_name, verdict, summary, data_snapshot)
```

Batch path: `tasks.tick_summary_generation(batch_size=5)` picks the `batch_size` bootstrapped
companies with the oldest (or absent, `nulls_first=True`) summary and fans out
`generate_summary_single.delay(symbol)` for each.

### Read endpoints

| Endpoint | View | Notes |
|---|---|---|
| `GET /api/companies/{symbol}/summaries/` | `CompanySummaryListView` | paginated history, `-generated_at` via model `Meta.ordering` |
| `GET /api/companies/{symbol}/summaries/latest/` | `CompanySummaryLatestView` | `404 NotFound` when none exist |
| `POST /api/companies/{symbol}/summaries/generate/` | `CompanySummaryGenerateView` | `202`, queues Celery |
| `GET /api/companies/summary-freshness/` | `GlobalSummaryFreshnessView` | age buckets of `generated_at` across all companies |

`CompanySummarySerializer` exposes **only** `id, generated_at, model_name, verdict, summary`.
`data_snapshot` is persisted but never served - the UI cannot show what the verdict was based on.

### Frontend surface

`frontend/src/components/companies/AiSummaryTab.tsx`, rendered as the **AI Summary** tab on
`/companies/$id`. Left rail lists past summaries (verdict chip + date + model), right pane renders
the raw `summary` text as `whitespace-pre-wrap`. A "Generate New Summary" button calls
`triggerSummaryGeneration`. API fns in `src/api/companies.ts`: `getLatestSummary`,
`getSummaryList`, `triggerSummaryGeneration`, `getSummaryFreshness`. Type in
`src/types/companies.ts::CompanySummary`.

Because generation is fire-and-forget, the button optimistically spins and the UI polls the list -
there is no run id, no progress, and no failure surface.

## What the model is told

`_SUMMARY_SYSTEM_PROMPT`: *"You are a professional equity analyst ... write a concise investment
summary (150-250 words). End with a single line exactly like this: `VERDICT: <BUY|HOLD|SELL|
INSUFFICIENT_DATA>`. Base the verdict only on the data provided."*

The user message (AAPL, 2026-09-16) is **~2.6k characters / ~650 tokens** across these sections:

`Valuation` (market_cap, trailing_pe, forward_pe, price_to_book, peg_ratio, beta, 52w high/low) -
`Profitability` (profit/gross/operating margins, ROE, ROA) - `Growth` (revenue + earnings YoY) -
`Leverage & Liquidity` (debt_to_equity, current_ratio, quick_ratio) - `Dividends` (yield,
payout_ratio) - `Analyst Consensus` (recommendation, mean score, opinions, target low/mean/high) -
`Short Interest` (short_ratio, short_pct_of_float) - `Last Earnings` (date, reported vs estimated
EPS, surprise_pct) - upcoming earnings date - `Annual Financials` (5 period_ends x 7 metrics) -
`Quarterly Financials` (4 quarters x 3 metrics) - `Recent Dividends` (last 2 payments).

## Baseline measurements (2026-09-16)

DB: 527 companies, all bootstrapped; 14,085 snapshots; **1,236 summaries already generated**.

Verdict distribution across all 1,236 persisted summaries:

| verdict | count | share |
|---|---|---|
| `buy` | 742 | 60.0% |
| `hold` | 475 | 38.4% |
| `sell` | **13** | **1.1%** |
| `insufficient_data` | 6 | 0.5% |

**A 60% buy rate with a 1% sell rate is the headline quality problem.** The model almost never says
sell. Any replacement must be measured against this distribution, not just against prose quality.

Models used: `qwen3:8b` (1,195), `analysis-assistant:latest` (41).

Five fresh baseline runs (AAPL, MSFT, KO, XOM, JPM) on `qwen3:8b`, ~5s each after warm-up,
prompts 2.2-2.4k chars: **all five returned `buy`**. Full text plus the collected misquotes in
[`baselines/ai-summary-2026-09-16.md`](baselines/ai-summary-2026-09-16.md).

## Findings

### 1. Unit bugs feed the model badly wrong numbers (highest severity)

`_fmt(value, pct=True)` multiplies by 100. That is correct for yfinance fields stored as
**fractions**, and wrong for the ones stored as **percent**. Three fields are wrong:

| Field | Stored (AAPL) | True meaning | Rendered in prompt |
|---|---|---|---|
| `dividend_yield` | `0.34` | 0.34% | **`34.0%`** (100x too high) |
| `EarningsDate.surprise_pct` | `6.74` | +6.74% | **`674.0%`** (100x too high) |
| `debt_to_equity` | `78.445` | 0.78x | **`78.44`** (rendered raw; read as 78x) |

Correct as-is (genuine fractions): `profit_margins`, `gross_margins`, `operating_margins`,
`return_on_equity`, `return_on_assets`, `revenue_growth`, `earnings_growth`, `payout_ratio`,
`short_pct_of_float`.

Confirmed across AAPL/MSFT/KO/XOM/JPM: `dividend_yield` = 0.34 / 0.73 / 2.44 / 2.69 / 1.71 (all
already percent), `surprise_pct` = 6.74 / 11.81 / 4.05 / 13.26 / 5.86.

The baseline runs confirm the model consumes these as real facts and reads them as **bullish**:
*"KO offers a high dividend yield of 244.0%"*, *"With a 269% dividend yield ... XOM offers
significant income generation"*, *"the recent earnings surprise of 674% highlights potential
upside"*. Worst of all, JPM: *"The dividend yield is unusually high at 171.0%, **likely due to a
special dividend**"* - rather than flagging an impossible number, the model invented a cause for a
rendering bug.

The `debt_to_equity` case is the most damaging, because `CLAUDE.md`'s own domain guidance says
">2.0 is high risk" - so on every single company the model is comparing a percent against a ratio
threshold and sees catastrophic leverage. It plausibly learns to ignore the field entirely, which
would explain part of the 1% sell rate.

### 2. No current price anywhere in the prompt

`target_low/mean/high_price` are supplied with **no close price to compare them to**, so implied
upside - the single most actionable analyst number - cannot be computed. `PriceBar` is never
queried; `fifty_day_average` / `two_hundred_day_average` are omitted, so there are no technicals
either.

### 3. No peer or sector context

Every number is absolute. `tools.industry_analysis` / `sector_analysis` already compute
avg/median/min/max across a peer group and are **not used**. (Since issue #9 they report
median/p25/p75/min/max and no mean - see the end of this document.) A P/E of 30 is meaningless without
the industry median; this is the largest single accuracy win available.

### 4. Field coverage gap

`CompanySnapshot` has 70 non-bookkeeping fields. `_assemble_company_data` reads **26**; 44 are
omitted, including `trailing_eps`, `forward_eps`, `free_cashflow`, `operating_cashflow`,
`total_cash`, `enterprise_to_ebitda`, `enterprise_to_revenue`, `price_to_sales`, `ebitda_margins`,
`earnings_quarterly_growth`, `week52_change`, `sandp52_week_change`, `fifty_day_average`,
`two_hundred_day_average`, the five governance risk scores (`audit_risk`, `board_risk`,
`compensation_risk`, `shareholder_rights_risk`, `overall_risk`), `held_pct_institutions`,
`held_pct_insiders`, `five_year_avg_dividend_yield` and `recommendations_breakdown`.

Separately, `apps/llm_analysis/chain.snapshot_metrics` - the helper behind the `company_snapshot`
**agent tool** - returns only **10** of the 70. Every agent (ReAct, plan-execute, orchestrator,
multiagent, DAG, autonomous) is therefore blind to 60 ingested fields.

Models never read at all by the summary path: `PriceBar`, `InstitutionalHolderSnapshot`,
`OptionsExpiry` / `OptionsContract`, `CompanySyncRecord`.

### 5. Thin slices of the data that is included

- `EarningsDate`: only the **single** most recent reported quarter. No beat/miss streak, though
  the rows are all there.
- `Dividend`: the last **2** payments only - not enough for a trailing-12-month yield, a growth
  rate, or a coverage ratio.
- `ShortInterest`: current values only; `shares_short_prior_month` is stored but the
  month-over-month change is never computed.

### 6. Structural weaknesses

- **No freshness gate.** `CompanySyncRecord` is never consulted. A company whose snapshot is
  months stale gets a confident verdict anyway.
- **Verdict by regex.** `_parse_verdict` reads a trailing text line. A model that reasons its way
  to "sell" but formats the line wrong silently becomes `insufficient_data`.
- **Single sample, no confidence.** One call at default temperature. `CompanySummary` has no
  confidence field, so a coin-flip hold and a unanimous sell look identical.
- **No self-check.** Nothing verifies that a claim in the prose maps to a number in the data.
- **Not auditable.** `data_snapshot` is persisted but not serialized, and there is no per-section
  trace - the summary is one opaque blob.
- **Pre-formatted strings.** `_assemble_company_data` stores `"$3.44T"` / `"N/A"`, not numbers, so
  `data_snapshot` cannot be recomputed against or diffed numerically.
- `CompanySummary` uses an auto-increment PK, unlike the UUID PKs mandated elsewhere by
  `CLAUDE.md`.

## What this implies for the rewrite

Ordered by expected impact:

1. Fix the three unit bugs (#1) - wrong inputs cap every downstream improvement.
2. Add peer-relative context (#3) and the current price (#2).
3. Widen `snapshot_metrics` and add the missing tools (#4, #5).
4. Replace the single call with the voted pipeline, which supplies the missing confidence,
   auditability and freshness gate (#6).

---

## What issue #3 changed (2026-09-16)

The path is still **one LLM call** from `services.generate_company_summary`. No new app, module,
model, endpoint or agent kind was added. What changed:

**Phase 1 - the numbers.**

- `dividendYield`, `fiveYearAvgDividendYield` and `debtToEquity` are divided by 100 at
  **ingestion** (`YFinanceClient.get_snapshot`, plus the raw-backfill path in
  `services.backfill_snapshot_fields`), so every ratio on `CompanySnapshot` is now a fraction.
  Migration `companies/0012_backfill_percent_to_fraction` rescales the rows written before that
  (reversible). `EarningsDate.surprise_pct` deliberately stays in **percent** - the earnings chart
  reads it directly - and renders through the new `_fmt_already_pct`. The convention is documented
  on `get_snapshot` and at the top of the summary section in `services.py`.
- `_assemble_company_data` now stores **numbers**, never pre-formatted strings; `_build_prompt_text`
  formats, driven by `_SECTION_SPECS` `(key, label, kind)` tuples. `data_snapshot` is therefore
  diffable and recomputable.
- New inputs: latest `PriceBar` close + position in the 52-week range + 50/200-day averages +
  `week52_change` vs `sandp52_week_change`; **implied upside** vs `target_mean_price` computed in
  Python (`None`, never 0, when either side is missing); a **peer benchmark** (company value beside
  the peer median for P/E, P/B, margins, ROE, D/E) built from `llm_analysis.tools.aggregate_snapshots`
  - renamed from `_aggregate_snapshots` so the peer maths lives in one place - over the industry,
  falling back to the sector below 3 peers and omitted when neither has any; last 4 reported
  quarters with a beat count; trailing-12-month dividend total and EPS coverage; short-interest
  month-over-month change; and the previously omitted `free_cashflow`, `total_cash`,
  `enterprise_to_ebitda`, `price_to_sales`, `ebitda_margins`, `earnings_quarterly_growth`,
  `trailing_eps` / `forward_eps`.

**Phase 2 - the verdict and a freshness gate.**

- The `VERDICT:` line and `_VERDICT_RE` are gone. The call passes `_SUMMARY_FORMAT` as Ollama's
  `format` schema and `_parse_summary_response` parses
  `{verdict, confidence, summary, key_drivers, key_risks}` tolerantly via
  `llm_analysis._json.parse_json_object`. Non-JSON, a missing verdict or an out-of-choices verdict
  all degrade to `insufficient_data`; `confidence` is clamped into 0-1 or nulled, never persisted raw.
- The system prompt now carries explicit **sell criteria** (peer-relative valuation, margin
  compression, coverage below 1.5x, deteriorating balance sheet, negative implied upside), requires
  every claim to cite a supplied number, and forbids inventing an explanation for an implausible
  value - the JPM "special dividend" failure.
- `CompanySummary` gained `confidence`, `key_risks`, `key_drivers` (migration `companies/0013`).
- **Freshness gate**: `_stale_sync_reasons` checks `CompanySyncRecord` for `snapshot` / `price` /
  `financials` against windows on the `LLMSettings` singleton
  (`summary_snapshot_max_age_days` 7, `summary_price_max_age_days` 3,
  `summary_financials_max_age_days` 120, seeded from `SUMMARY_*_MAX_AGE_DAYS` env vars). Stale or
  never-synced -> an `insufficient_data` row naming the reason, with **zero LLM calls**.
- `CompanySummarySerializer` additively exposes `confidence`, `key_risks`, `key_drivers` and
  `data_snapshot`.

**Phase 3 - the UI.** `AiSummaryTab` renders the confidence beside the verdict chip, key drivers and
key risks as lists, an explicit stale-data panel (from `data_snapshot.stale_data`) instead of a bare
`INSUFFICIENT DATA` chip, and a collapsible **Data used** panel over `data_snapshot`. All new fields
are optional on `types/companies.ts::CompanySummary`, so pre-Phase-2 rows still render.

**Tests.** `apps/companies/tests/test_summary_inputs.py` (ingestion units, the backfill migration
functions, assembled inputs, the peer benchmark, and `TestPromptUnitRegressions` pinning the exact
baseline misquotes - 244% yield, 674% surprise, 78x D/E), a rewritten
`test_services.py::TestGenerateCompanySummary` (structured parse, malformed/missing/out-of-choices
verdicts, confidence clamping) plus `TestSummaryFreshnessGate` (per-sync-type windows, missing
records, `chat` asserted not called), serializer + view tests for the additive fields, settings tests
for the freshness windows, and 8 `AiSummaryTab` component tests including a pre-Phase-2 row.

**Still open** (follow-ups, not in #3): re-measure the verdict distribution across a regenerated
corpus and add 3-way voting on the verdict field if the 60/38/1 skew survives; the six new agent
tools from #1's Phase 2; `CompanySummary`'s auto-increment PK.

## What issue #9 changed in the peer benchmark (2026-09-28)

[Issue #9](https://github.com/bthek1/Market_Analyzer/issues/9) reshaped `aggregate_snapshots`, the
helper this benchmark shares with the agents' `sector_analysis` / `industry_analysis` tools.

**Phase 1 - no change here, and a test proves it.** `_stats` no longer returns `avg`. It returns
`{median, p25, p75, min, max, n}`. The summary never read `avg`; it reads only `median`, so
`TestPeerBenchmark::test_peer_median_matches_the_plain_median_for_every_metric` pins all seven
peer medians to the values they had before.

**Phase 2 - a deliberate change to a shipped number.** A negative `trailing_pe`, `forward_pe` or
`price_to_book` (`tools.VALUATION_RATIOS`) means losses or negative book equity, not a low
valuation. Negatives are now **excluded from the peer distribution and counted**, and the count
shows up as `peer_negative` on the metric row in `data_snapshot`. So `peer_median` for those three
ratios **rises** wherever a peer had a negative value. Measured on the local Technology sector
(same data, before vs after), P/B's median moves from 7.54 to 8.37 with 5 companies excluded, and
forward P/E's from 18.30 to 18.40 with 1 excluded. Trailing P/E is unchanged because no company has
a negative one. `return_on_equity`, `profit_margins` and `debt_to_equity` keep their negatives, because
a negative value there is meaningful and comparable. That rule is pinned explicitly, since the easy
mistake is to apply it to every metric. If every peer in a group is negative, the metric is `None`
("N/A") rather than a number.

**A company whose OWN P/E or P/B is negative gets no peer comparison.** The benchmark line reads
`Trailing P/E: company -15.00 (negative - losses or negative equity, no meaningful peer comparison)`
instead of `... vs peer median 20.00`, which would read as "far cheaper than peers". The raw
`peer_median` is still stored in `data_snapshot` so the row stays diffable. Only the prompt line
withholds it. Zero is not negative: a company at exactly 0.00 is still compared, and a test pins
that boundary. An all-negative peer group renders `vs peer median N/A`.

**Tests** (`test_summary_inputs.py::TestPeerBenchmark`): all seven medians unchanged for a
non-negative fixture; a negative-P/B peer raises the median and is counted; a negative-ROE peer
still counts; an own negative P/E withholds the median; an own negative ROE and an own zero P/E do
not; an all-negative group reads N/A. The uniform-rule mutation (exclude negatives for every metric)
and the `<= 0` mutation each fail at least one of them. The system prompt, the sell criteria and the verdict logic are untouched.
`TestPromptUnitRegressions` passed unchanged.

## Issue #11: nothing changes here, on purpose (2026-09-29)

[Issue #11](https://github.com/bthek1/Market_Analyzer/issues/11) re-expressed the fraction-valued
ratios (ROE, profit margins, dividend yield) as PERCENT under `*_pct` names in everything an agent
model reads: `chain.snapshot_metrics` and the `sector_analysis`/`industry_analysis` observations.
**`aggregate_snapshots` was deliberately left returning fractions**, and the conversion is done
at the tool boundary (`tools._agent_units`) instead. This benchmark is the reason: it reads
`aggregate_snapshots` directly, and `_build_prompt_text` renders its own percents from
`_SECTION_SPECS` with the `pct` kind. Converting inside the shared helper would have multiplied
twice, so the summary would print a 23.26% ROE median as 2,326%.
`test_react_tools.py::TestPercentUnits::test_the_summary_benchmark_still_gets_fractions` pins it,
and `TestPromptUnitRegressions` passed unchanged.

The summary never had issue #11's bug. Every value it sends goes through an explicit formatter,
so the model is given "23.26%" and never 0.2326. The agent tools emit raw JSON and had no unit
anywhere, which is why they needed the fix and this pipeline did not.

## Issue #13: the peer-group choice moved, and the behaviour did not (2026-09-29)

`_peer_group` now delegates to `llm_analysis.tools.peer_group`. The agents' new `peer_comparison`
tool needs exactly this benchmark rule: the industry, falling back to the sector when the industry
has fewer than `MIN_PEERS=3` other companies, with the company always excluded. It now has one home,
as the peer maths did in `aggregate_snapshots`. `_MIN_PEERS` became `tools.MIN_PEERS`. The summary's
benchmark and its tests are unchanged, and
`test_react_tools.py::TestPeerComparisonTool::test_peer_group_is_the_summary_rule` pins that both
callers pick the same group.

The agents' version goes a step further than the summary: it computes the RELATION (`vs_median`
"18% below", a quartile band and a per-metric reading) rather than handing over two numbers. The
summary has not been measured for the backwards-comparison error that motivated it. If it shows
up there, the same `compare_metric` output could be rendered into `_build_prompt_text`'s benchmark
lines.

