---
name: ai-summary
description: "AI company summary (CompanySummary): the fraction-vs-percent unit convention, the structured verdict, and the freshness gate — issue #3, 2026-09-16"
metadata:
  type: project
---

## AI Company Summary — what issue #3 changed (2026-09-16)

`apps/companies/services.generate_company_summary` — **one** blocking LLM call, fire-and-forget via
Celery, rendered on the **AI Summary** tab of `/companies/$id`. Issue #3 **superseded issue #1's
Phases 3-5**: the proposed `equity_report.py` module + `AgentRun(kind="equity_report")` + lens
fan-out + voting + eval-opt loop were all **dropped**. The quality problem was the INPUT, not the
topology, and a fixed single-ticker report does not need run/step persistence.

**The unit bug is the fact worth remembering.** Every ratio on `CompanySnapshot` is a **FRACTION**
(0.0034 = 0.34%). yfinance is inconsistent: `profitMargins`/`returnOnEquity` arrive as fractions,
but `dividendYield`, `fiveYearAvgDividendYield` and `debtToEquity` arrive in **PERCENT**. They are
now divided by 100 **at ingestion** (`YFinanceClient.get_snapshot` *and* the raw-backfill path in
`services.backfill_snapshot_fields` — two writers, both had to change), with migration
`companies/0012_backfill_percent_to_fraction` rescaling existing rows. `EarningsDate.surprise_pct`
is the one deliberate exception: it stays in **percent** because the earnings chart reads it
directly, and renders via `_fmt_already_pct`, never `_fmt(pct=True)`.

Before the fix the model was told KO yielded 244%, AAPL carried 78x leverage and a quarter beat by
674% — and it believed it, inventing a special dividend to explain JPM's impossible "171% yield".
`apps/companies/tests/test_summary_inputs.py::TestPromptUnitRegressions` pins the corrected strings.

Other structural facts:

- `_assemble_company_data` stores **numbers**, never pre-formatted strings; `_build_prompt_text` is
  the only formatter, driven by `_SECTION_SPECS` `(key, label, kind)` tuples.
- Peer benchmark reuses `llm_analysis.tools.aggregate_snapshots` (renamed from `_aggregate_snapshots`
  to be public) over the industry, falling back to the sector below 3 peers, company excluded from
  its own median, omitted when neither group has peers with snapshots.
- The verdict is **Ollama structured output** (`_SUMMARY_FORMAT` passed as `format`), parsed
  tolerantly via `llm_analysis._json.parse_json_object`. No `VERDICT:` line, no regex. Anything
  unusable degrades to `insufficient_data`; `confidence` is clamped into 0-1 or nulled.
- **Freshness gate**: stale or never-synced `CompanySyncRecord` for `snapshot`/`price`/`financials`
  (windows on the `LLMSettings` singleton, seeded from `SUMMARY_*_MAX_AGE_DAYS`) writes an
  `insufficient_data` row with **zero LLM calls**; reasons land in `data_snapshot["stale_data"]`.

Still open: the baseline verdict skew (60% buy / 38% hold / **1% sell** across 1,236 rows) has NOT
been re-measured since the fix — regenerating the 5 baseline tickers needs live Ollama and the prod
dataset. If the skew survives, 3-way voting on the verdict field alone is the next increment. See
`docs/project_docs/ai-summary-pipeline.md` (audit + "What issue #3 changed") and [[project-state]].

**Why:** The percent-vs-fraction split is invisible in the schema and silently corrupts any new
reader of those three fields.
**How to apply:** When touching `CompanySnapshot` ratios or the summary prompt, assume fractions,
and normalise any NEW percent-scaled yfinance field at ingestion rather than at render time.

**Issue #9 (2026-09-28) changed the peer benchmark on purpose.** `aggregate_snapshots` now
excludes NEGATIVE trailing/forward P/E and P/B (`tools.VALUATION_RATIOS`) from the peer median and
counts them as `peer_negative`, so those medians RISE where a peer had losses or negative equity
(local Technology P/B: 7.54 -> 8.37). A company whose OWN P/E or P/B is negative is rendered with
"no meaningful peer comparison" instead of a median. ROE, margins and D/E keep their negatives.
**How to apply:** do not "simplify" by applying the negative rule to every metric. A test pins
exactly the three ratios.

**Issue #11 (2026-09-29):** the AGENT tools now emit ROE/margins/yield as percent `*_pct`, but
`aggregate_snapshots` still returns FRACTIONS because this benchmark reads it and formats its own
percents. The conversion lives at the tool boundary (`tools._agent_units`).
**How to apply:** never move the `*_pct` conversion into `aggregate_snapshots`, or the summary
will print 2,326%. A test pins it.

**Issue #13 (2026-09-29):** `_peer_group` delegates to `llm_analysis.tools.peer_group` (industry,
falling back to the sector below `tools.MIN_PEERS=3`, company excluded), shared with the agents'
`peer_comparison` tool. Behaviour is unchanged and pinned by a test. Not yet measured: whether the
summary also states comparisons backwards. `tools.compare_metric` is the ready-made fix if it does.
