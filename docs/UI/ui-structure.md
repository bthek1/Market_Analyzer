# UI Structure

## Page Tree

```
/ (Dashboard)
├── /login
├── /register
├── /companies
│   └── /companies/$id  (Company Detail)
├── /market-map
├── /tasks
├── /redis
├── /agents        (LLM workflow runner)
├── /browse        (browser agent — live web search)
├── /knowledge     (concept graph)
└── /code-graph    (graphify code graph)
```

---

## Layout

### AppShell

Wraps every authenticated page. Layout is **sidebar-left**, not a nav topbar:

```
+--------------+--------------------------------------------+
| Sidebar      |  topbar (h-14): hamburger (mobile) · clock  |
|  logo+toggle |                 · email · Admin · Logout    |
|  Dashboard   |--------------------------------------------|
|  Companies   |                                            |
|  ...         |  <main> (max-w-7xl, px-6, py-8)            |
|  Code Graph  |                                            |
+--------------+--------------------------------------------+
| StatusBar (h-9, full width)                               |
+-----------------------------------------------------------+
```

- **Sidebar** (`components/layout/Sidebar.tsx`) — logo mark + "Stock Market" wordmark → `/`,
  then one icon+label link per entry in `components/layout/nav.ts` (`NAV_LINKS`, the single
  source of truth for navigation): Dashboard · Companies · Market Map · Tasks · Redis ·
  Agents · Browse · Knowledge · Code Graph.
  - **Collapsible** — the toggle switches between a `w-60` panel and a `w-14` icon rail
    (labels become `sr-only`, `title` supplies the tooltip). The flag lives in
    `store/ui.ts` and is persisted to `localStorage` (`sidebar_collapsed`), because every
    route renders its own `<AppShell>` and so the shell remounts on navigation.
  - **Active state** — `isNavActive()` marks sub-routes active on their parent link
    (`/companies/$id` highlights "Companies"); `/` matches only exactly. Rendered as
    `aria-current="page"`.
  - **Mobile (`< md`)** — the sidebar becomes an overlay drawer opened by the topbar
    hamburger, with a backdrop; following a link or clicking the backdrop closes it.
- **Topbar** (sticky, `h-14`) — hamburger (mobile only), clock, user email, Admin link,
  Logout button. It holds **no navigation**.
- **StatusBar** — full-width `h-9` footer showing background service status.
- **`<main>`** content slot (max-w-7xl, px-6, py-8).

### FullBleed

`components/layout/FullBleed.tsx` lets a page escape `main`'s padding and fill the viewport
between the header and the status bar (`-mx-6 -my-8 h-[calc(100vh-5.75rem)]`). Used by
`/knowledge`. It is deliberately **content-column width, not `w-screen`** — a viewport-width
bleed would sit underneath the sidebar.

Auth guard lives in `__root.tsx`: unauthenticated users are redirected to `/login`; authenticated users on `/login` or `/register` are redirected to `/`.

---

## Pages

### `/` — Dashboard

**Components:** `StatCard`, `BootstrapProgress`, `QuickNavCard`

**Stat row (4 cards):**

| Card | Data source | Link |
|---|---|---|
| Companies Tracked | `useCompanySearch({ page_size: 1 })` total count + `is_bootstrapped=true` count → bootstrap progress bar | `/companies` |
| Sectors | `useSectors()` count | `/market-map` |
| Market Map | Static description | `/market-map` |

**Quick Access grid (4 cards):**
Company Search · Market Map · Task Monitor · Redis Monitor

---

### `/login` — Login

Form: email + password → JWT pair → stored in `localStorage`.  
Zod schema validated via React Hook Form + `zodResolver`.

### `/register` — Register

Form: email + password → create account.

---

### `/companies` — Company List

**Layout:** AppShell wrapping a server-side paginated table.

**Filters (top bar):**
- Text search (300 ms debounce → `search` param)
- Sector `<select>` → `sector` param; resets industry filter when changed
- Industry `<select>` (filtered to chosen sector) → `industry` param
- Exchange `<select>` (NYSE · NASDAQ · AMEX · NYSE_ARCA · LSE · ASX · TSX · OTHER)
- Bootstrapped toggle checkbox → `is_bootstrapped` param

**`CompanyTable`** columns:
Symbol · Name · Exchange · Sector · Industry · Bootstrapped badge

Pagination: prev / page N of M / next (25 rows per page).  
Column headers are clickable → sets `ordering` param (toggle asc/desc).  
Row click → navigate to `/companies/$id`.

---

### `/companies/$id` — Company Detail

**Header:**
- Symbol (large, bold) · full name
- Badges: exchange · currency · sector · industry · bootstrapped status

**`CompanyTabs`** — horizontal tab bar (scrollable on mobile):

```
Overview | Financials | Market Data | Ownership | Dividends | Earnings | ESG | Options
```

#### Tab: Overview

- **Key metrics grid** — snapshot fields: market cap, trailing/forward P/E, P/B, EPS (trailing/forward), debt/equity, ROE, profit margins, dividend yield, beta, 52-week high/low
- **52-week range bar** — visual bar showing current price relative to 52w low/high
- **Analyst targets** — recommendation key badge, mean/high/low target prices, num analyst opinions
- **Governance risk scores** — audit, board, compensation, shareholder rights, overall (1–10, lower is better)
- **Company profile table** — address, phone, website, IR website, employees, description
- **Officers list** — name + title from `officers` JSONField
- **`SyncPanel`** — data type: `profile` + `snapshot`

#### Tab: Financials

- **Statement type toggle:** Income · Balance Sheet · Cash Flow
- **Period toggle:** Annual · Quarterly
- **Revenue + Net Income bar chart** (ECharts) — dual-bar, $B formatted y-axis
- **Pivoted metrics table** — rows = metric names, columns = period_end dates; values formatted as compact numbers
- **`SyncPanel`** — data type: `financials`

#### Tab: Market Data

- **Stat cards row** — 52-week high/low, average volume, shares outstanding, float shares, week 52 change, S&P 500 52-week change
- **`PriceChart`** — candlestick OHLCV chart (ECharts); date range buttons: 1M · 3M · 6M · 1Y · All; loads paginated `PriceBar` data
- **Moving averages** — 50-day and 200-day averages from snapshot
- **Short Interest table** — date, shares short, short % of float, short ratio, prior-month comparison; `SyncPanel` for `short_interest`
- **`SyncPanel`** — data type: `prices`

#### Tab: Ownership

- **Ownership summary cards** — % held by institutions, % held by insiders
- **Institutional Holders table** — holder name, shares, % out, value; from latest `InstitutionalHolderSnapshot`
- **`SyncPanel`** — data type: `institutional`

#### Tab: Dividends

- **Dividend yield + payout ratio cards**
- **Dividend history table** — date, amount per share; paginated
- **Dividend chart** (ECharts) — bar chart of dividend amounts over time
- **`SyncPanel`** — data type: `dividends`

#### Tab: Earnings

- **Upcoming earnings** — date, EPS estimate; `is_upcoming=true`
- **Historical earnings table** — date, EPS estimate, reported EPS, surprise %
- **`SyncPanel`** — data type: `earnings`

#### Tab: ESG

- **ESG score cards** — total ESG, environment, social, governance scores + performance tier badge
- **`SyncPanel`** — data type: `esg`

#### Tab: Options

- **Expiry date selector** — dropdown of available expiry dates
- **Options chain table** — strike, last price, bid, ask, volume, open interest, IV, in-the-money badge; toggled Call / Put
- **`SyncPanel`** — data type: `options`

#### `SyncPanel` (shared component)

Appears on every tab. Shows:
- Last synced timestamp for this data type (from `SyncStatus`)
- "Sync now" button → fires Celery task via `POST /api/companies/$id/sync/$dataType/`
- Task progress badge: PENDING · SUCCESS · FAILURE (polls every 2 s until terminal)

---

### `/market-map` — Market Map

- **Chart type toggle:** Sunburst · Treemap
- **`SectorIndustrySunburst`** (ECharts) — two-ring: outer = sectors, inner = industries; sized by market cap; click sector → sets `activeSector` filter
- **`SectorIndustryTreemap`** (ECharts) — drilldown treemap: sector → industry → company; sized by market cap
- **Active sector filter** — clicking a sector in either chart filters the table below
- **Industry search** — text input; 300 ms debounce
- **Industry + Company table** — paginated (20/page), columns: industry name, sector, company count; prev/next pagination

---

### `/tasks` — Celery Task Monitor

**Tabs:** Recent Executions · Schedules

**Recent Executions (`TaskResultsTable`):**
- Status filter: ALL · PENDING · STARTED · SUCCESS · FAILURE
- Table: task name · status badge · started at · runtime · result preview
- Auto-refresh every 5 s while any task is in a non-terminal state

**Schedules (`ScheduledTasksTable`):**
- Table: task name · schedule (cron expression) · last run · next run · enabled toggle

---

### `/redis` — Redis Monitor

**Tabs:** Server Info · Keys

**Server Info (`RedisInfoCards`):**
- Cards: Redis version · uptime · connected clients · used memory · peak memory · keyspace hits/misses · total commands processed

**Keys (`RedisKeysTable`):**
- Prefix filter input → debounced `GET /api/redis/keys/?prefix=…`
- Table: key · type · TTL; click row → opens `RedisKeyValueDrawer`

**`RedisKeyValueDrawer`:**
- Slide-in panel showing raw key value (JSON formatted if parseable)

---

### `/agents` — LLM Workflow Runner

Runs the ten `llm_analysis` workflows (chain · route · parallel · react · eval_opt · plan_exec ·
orchestrator · multiagent · dag · autonomous) and streams their steps live.

- **Query box + workflow selection** — pick one or many; each selected workflow gets its own result panel
- **SSE streaming** — every workflow POST streams typed events (`step` / `task` / `iteration` /
  `worker` / `node` / `cycle` / `result`); panels render steps as they arrive
- **Stop** — per-panel button, a global Stop next to Run, and a Stop action on running history
  rows. Cancellation goes through the DB (`POST /api/llm/runs/stop/`), so it works across processes
- **History sidebar** — docked left, open by default; lists past runs by kind
- **Session persistence** — mode, selected workflows, query and per-type run ids live in
  `localStorage` (`agentsSession.ts`). On reload the page restores them and **polls the detail
  endpoints** for any still-`running` run until it reaches a terminal status, so a refresh never
  orphans a run
- **Settings drawer** (`SettingsDrawer` / `LLMSettingsForm`) — edits the `LLMSettings` singleton

---

### `/browse` — Browser Agent (live web search)

A **standalone page**, deliberately not a mode on `/agents`: that page compares LLM workflows over
one query side by side, while a browser run is a single minutes-long search whose output is visual.
It shares no state, no session store and no history feed with the Agents workspace.

- **Search box** — the page's anchor, autofocused; provider and max-steps hide behind an
  "Options" disclosure so the default path is type-and-enter
- **Step timeline** — one row per browser action: the action name, page URL + title, the agent's
  evaluation of the previous step, and a screenshot thumbnail (click to enlarge)
- **Answer + Sources** — markdown answer plus the de-duplicated list of URLs actually visited,
  with a badge for why the run stopped (answered / ran out of steps / ran out of time)
- **Stop** — replaces Run while streaming; goes through the same `POST /api/llm/runs/stop/`
- **History sidebar** — reads `/api/llm/browser/history/` directly. Browser runs do **not** appear
  in the Agents page's combined feed
- **Session persistence** — last query + run id in `localStorage` under `browseSession` (its own
  key, not `agentsSession`); on reload a still-`running` run is polled until it settles
- **Disabled empty state** — the feature ships off (`browser_enabled`). The page renders a card
  in the shape of `/code-graph`'s "not built" screen, never a raw 503
- **Screenshots** are fetched through the authenticated client and rendered from an object URL:
  the endpoint is owner-checked, so a plain `<img src>` would 401

---

### `/knowledge` — Concept Graph

The self-expanding `knowledge_graph` concept graph.

- **`ConceptGraph`** (ECharts) — four layouts: force · hierarchy · tree · sankey. Nodes are
  coloured and sized by recursive structural **`reach`** (not raw connections); not-yet-expanded
  frontier nodes are drawn as a pale tint (never invisible white). Settled positions are pinned so
  the layout does not reshuffle on refetch
- **Expand-to-degree** — per-concept 1st / 2nd / 3rd buttons; a degree button fades once its whole
  ball is already expanded
- **Selected-concept panel** — description plus `negative_description` ("Not to be confused
  with: …"), the homonym contrast signal
- **Overlay panels** — Build · Concept · Auto-expand
- **Controls** — Auto-expand top 5 hubs · Clear queue (stop) · Live polling · Rerank & prune ·
  Reduce edges

---

### `/code-graph` — Code Graph

The **graphify** code-knowledge graph: this repository parsed into nodes and edges by tree-sitter
AST extraction. A developer tool, unrelated to `/knowledge` despite the similar name.

- **`CodeGraph`** (ECharts force layout) — colour = **layer** (backend / frontend / infra / other),
  size = degree, edge dash = **confidence** (`EXTRACTED` solid, `INFERRED` dashed). Colour is
  deliberately *not* graphify's Leiden community: the repo yields ~400 of them and a categorical
  scale is unreadable past a handful. Only the top ~25 hubs carry a permanent label
- **Filter row** — search (symbol or path) · layer · module · relation · node limit ·
  "Show inferred edges". Defaults to `EXTRACTED` only, so guesses are opt-in
- **Selected-node panel** — file:line, layer / module / community / degree, then "Used by" and
  "Uses" lists; clicking a neighbour walks the graph
- **Empty state** — `graphify-out/` is gitignored, so a fresh clone (and prod) gets a 404 with a
  hint; the page renders that as a card containing the build command, never an error
- **Legend** — always present (layer swatches + solid/dashed provenance key)

> **Known limitation — the frontend half of this graph is sparse.** Graphify does not resolve
> `tsconfig.json` path aliases, and this codebase mandates `@/` imports, so 73% of TypeScript
> nodes have no real edge (against 24% for Python). Filtering to `layer=backend` gives a
> readable graph; the unfiltered view shows the frontend as a cloud of near-isolated dots. This
> is upstream behaviour, not a bug in the page.

---

## Component Inventory

```
src/
├── components/
│   ├── layout/
│   │   ├── AppShell.tsx          — sidebar + topbar + main wrapper (re-exports LogoMark)
│   │   ├── Sidebar.tsx           — collapsible nav rail / mobile drawer
│   │   ├── nav.ts                — NAV_LINKS (+ icons) and isNavActive()
│   │   ├── LogoMark.tsx          — brand SVG (also used by login/register)
│   │   ├── FullBleed.tsx         — escape main's padding, fill the content column
│   │   ├── StatusIndicator.tsx   — coloured dot for task/sync state
│   │   └── StatusOverlay.tsx     — StatusBar footer
│   ├── companies/
│   │   ├── CompanyTable.tsx      — server-side paginated + filtered table
│   │   ├── CompanyTabs.tsx       — tab bar (reusable)
│   │   ├── OverviewTab.tsx       — snapshot metrics + profile
│   │   ├── MarketDataTab.tsx     — price chart + short interest
│   │   ├── FinancialsTab.tsx     — pivoted financials + ECharts bars
│   │   ├── DividendsTab.tsx      — dividend history + chart
│   │   ├── EarningsTab.tsx       — upcoming + historical earnings
│   │   ├── AiSummaryTab.tsx      — LLM-generated company summary
│   │   ├── OptionsTab.tsx        — options chain by expiry
│   │   ├── OwnershipTab.tsx      — institutional holders
│   │   ├── PriceChart.tsx        — ECharts candlestick OHLCV
│   │   ├── SectorIndustrySunburst.tsx   — two-ring ECharts sunburst
│   │   ├── SectorIndustryTreemap.tsx    — drilldown ECharts treemap
│   │   └── SyncPanel.tsx         — per-data-type sync trigger + status
│   ├── tasks/
│   │   ├── ScheduledTasksTable.tsx
│   │   ├── TaskResultsTable.tsx
│   │   └── TaskStatusBadge.tsx
│   ├── redis/
│   │   ├── RedisInfoCards.tsx
│   │   ├── RedisKeysTable.tsx
│   │   └── RedisKeyValueDrawer.tsx
│   ├── llm/
│   │   ├── ChatPanel.tsx          — streaming workflow result panel
│   │   ├── LLMSettingsForm.tsx    — edits the LLMSettings singleton
│   │   └── SettingsDrawer.tsx
│   ├── knowledge/
│   │   └── ConceptGraph.tsx       — force/hierarchy/tree/sankey concept graph
│   ├── codegraph/
│   │   └── CodeGraph.tsx          — force-layout graphify code graph
│   ├── browser/                  — /browse only (no overlap with the Agents page)
│   │   ├── SearchBar.tsx          — query input + Run/Stop + Options disclosure
│   │   ├── StepTimeline.tsx       — live step list + screenshot lightbox
│   │   ├── StepCard.tsx           — one browser action
│   │   ├── AnswerPanel.tsx        — markdown answer + Sources
│   │   ├── Screenshot.tsx         — auth-fetched screenshot (object URL)
│   │   └── RunHistory.tsx         — this page's own run history
│   ├── Markdown.tsx               — shared markdown renderer
│   └── ui/                       — shadcn base-nova primitives
│       ├── badge.tsx
│       ├── button.tsx
│       ├── card.tsx
│       ├── input.tsx
│       ├── label.tsx
│       ├── separator.tsx
│       └── table.tsx
└── routes/
    ├── __root.tsx                — auth guard + Outlet
    ├── index.tsx                 — Dashboard
    ├── login.tsx
    ├── register.tsx
    ├── companies.tsx             — layout route (Outlet only)
    ├── companies.index.tsx       — /companies list
    ├── companies.$id.tsx         — /companies/$id detail
    ├── market-map.tsx
    ├── market-map.utils.ts        — hierarchy/filter helpers
    ├── tasks.tsx
    ├── redis.tsx
    ├── agents.tsx                 — LLM workflow runner
    ├── browse.tsx                 — browser agent (live web search)
    ├── knowledge.tsx              — concept graph
    └── code-graph.tsx             — graphify code graph
```

---

## State Management Summary

| Concern | Tool |
|---|---|
| Server data (companies, snapshots, prices…) | TanStack Query (`useQuery` / `useMutation`) |
| Auth token | `localStorage` (`access_token` / `refresh_token`) |
| Auth user | Zustand (`src/store/auth.ts`) |
| Sidebar collapsed | Zustand (`src/store/ui.ts`), mirrored to `localStorage` (`sidebar_collapsed`) |
| Mobile drawer open | `useState` in `AppShell` (resets naturally on navigation) |
| Local UI state (active tab, filters, page) | `useState` in each route/component |
| Form state | React Hook Form + Zod schemas |

## Charting

All charts use **ECharts v6.1.0** via **echarts-for-react v3.0.6**.

| Chart | Component | Type |
|---|---|---|
| Price history (OHLCV) | `PriceChart` | Candlestick + volume bar |
| Market cap hierarchy | `SectorIndustrySunburst` | Sunburst (two-ring) |
| Market cap hierarchy | `SectorIndustryTreemap` | Drilldown treemap |
| Revenue + Net Income | `FinancialsTab` (inline) | Dual bar |
| 52-week price range | `OverviewTab` (inline) | Custom progress bar |
| Concept graph | `ConceptGraph` | Graph (force) · graph (hierarchy) · tree · sankey |
| Code graph | `CodeGraph` | Graph (force) |

**Graph-series conventions** (both graph components):

- Settled node positions are captured on the chart's `finished` event and **pinned** via a ref, so
  new data merges in place instead of triggering a full re-layout. The ref is read during render on
  purpose — it must not be reactive.
- Encoding is never colour-alone: `ConceptGraph` draws frontier nodes as a pale tint plus a dashed
  ring; `CodeGraph` uses solid vs dashed edges for `EXTRACTED` vs `INFERRED` and always shows a legend.
- Categorical colour is capped at a handful of values. `CodeGraph` colours by layer (4) rather than
  graphify's ~400 Leiden communities; palette slots are validated for colour-vision deficiency in
  both light and dark mode.
