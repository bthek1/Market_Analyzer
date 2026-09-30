import { http, HttpResponse } from "msw";
import type { RequestHandler } from "msw";
import type {
  Company,
  CompanySnapshot,
  CompanySummary,
  Dividend,
  EarningsDate,
  FinancialStatement,
  Industry,
  InstitutionalHolderSnapshot,
  OptionsChain,
  OptionsExpiry,
  PaginatedResponse,
  PriceBar,
  Sector,
  ShortInterest,
  SyncStatus,
} from "@/types/companies";
import type { PeriodicTask, TaskResult } from "@/types/tasks";
import type { RedisInfo, RedisKeysResponse, RedisKeyValue } from "@/types/redis";
import type { GlobalSyncFreshness, SyncFreshnessMatrix } from "@/api/companies";
import type {
  OllamaModel,
  ChainRunDetail,
  ChainRunSummary,
  LLMSettings,
  ReactRunDetail,
  ReactRunSummary,
} from "@/types/llm";

export const MOCK_LLM_MODELS: OllamaModel[] = [
  { name: "llama3.2:latest", size_gb: 2.0 },
  { name: "mistral:latest", size_gb: 4.07 },
];

export const MOCK_LLM_SETTINGS: LLMSettings = {
  base_url: "http://localhost:11434",
  main_model: "qwen3:8b",
  classifier_model: "qwen3:1.7b",
  embed_model: "nomic-embed-text",
  timeout: 60,
  num_parallel: 4,
  route_mode: "llm",
  route_threshold: 0.75,
  react_max_steps: 6,
  eval_max_iterations: 3,
  eval_threshold: 8,
  plan_max_steps: 20,
  plan_max_replans: 5,
  orch_max_workers: 4,
  multiagent_max_tools: 4,
  dag_max_nodes: 6,
  auto_max_cycles: 8,
  auto_max_subagents: 3,
  auto_subagent_steps: 3,
  auto_no_progress: 2,
  browser_enabled: true,
  browser_provider: "ollama",
  browser_model: "",
  browser_max_steps: 15,
  browser_timeout_s: 300,
  browser_headless: true,
  browser_allowed_domains: "*.google.com\n*.sec.gov",
  updated_at: "2026-06-11T00:00:00Z",
};

export const MOCK_LLM_CHAT_RESPONSE = { content: "Hello from Ollama!" };

export const MOCK_CHAIN_RUN_ID = "11111111-1111-1111-1111-111111111111";

export const MOCK_CHAIN_RUN_SUMMARY: ChainRunSummary = {
  id: MOCK_CHAIN_RUN_ID,
  query: "Analyse AAPL revenue",
  status: "done",
  model: "llama3.2:latest",
  created_at: "2026-06-09T10:00:00Z",
  completed_at: "2026-06-09T10:00:30Z",
};

export const MOCK_CHAIN_RUN_DETAIL: ChainRunDetail = {
  ...MOCK_CHAIN_RUN_SUMMARY,
  steps: [
    { id: "s1", step_id: "classify", label: "Classify Query", order: 0, status: "done", output: '{"intent":"analyse","tickers":["AAPL"],"time_horizon":"annual"}', error: "", started_at: "2026-06-09T10:00:01Z", completed_at: "2026-06-09T10:00:05Z" },
    { id: "s2", step_id: "research", label: "Gather Data", order: 1, status: "done", output: "[]", error: "", started_at: "2026-06-09T10:00:05Z", completed_at: "2026-06-09T10:00:10Z" },
    { id: "s3", step_id: "synthesise", label: "Synthesise", order: 2, status: "done", output: "Detailed analysis text.", error: "", started_at: "2026-06-09T10:00:10Z", completed_at: "2026-06-09T10:00:20Z" },
    { id: "s4", step_id: "format", label: "Format Report", order: 3, status: "done", output: "## Summary\nAAPL looks strong.", error: "", started_at: "2026-06-09T10:00:20Z", completed_at: "2026-06-09T10:00:30Z" },
  ],
};
export const MOCK_REACT_RUN_ID = "22222222-2222-2222-2222-222222222222";

export const MOCK_REACT_RUN_SUMMARY: ReactRunSummary = {
  id: MOCK_REACT_RUN_ID,
  query: "Is AAPL cheap?",
  max_steps: 6,
  status: "done",
  model: "llama3.2:latest",
  created_at: "2026-06-10T10:00:00Z",
  completed_at: "2026-06-10T10:00:20Z",
};

export const MOCK_REACT_RUN_DETAIL: ReactRunDetail = {
  ...MOCK_REACT_RUN_SUMMARY,
  output: "## Verdict\nAAPL is fairly valued.",
  error: "",
  steps: [
    { id: "r1", order: 0, thought: "I need AAPL valuation", tool: "company_snapshot", tool_args: { symbol: "AAPL" }, observation: '{"trailing_pe": 31.2}', is_answer: false, status: "done", error: null },
    { id: "r2", order: 1, thought: "I have enough to answer", tool: null, tool_args: null, observation: null, is_answer: true, status: "done", error: null },
  ],
};

export const MOCK_LLM_SUMMARISE_RESPONSE = { content: "Short summary." };
export const MOCK_LLM_ANALYSE_RESPONSE = { content: "Detailed analysis." };

export const MOCK_REDIS_INFO: RedisInfo = {
  redis_version: "7.2.4",
  uptime_in_seconds: 86400,
  connected_clients: 3,
  used_memory_human: "2.41M",
  used_memory_peak_human: "3.10M",
  mem_fragmentation_ratio: 1.12,
  total_commands_processed: 184321,
  instantaneous_ops_per_sec: 42,
  keyspace_hits: 1200,
  keyspace_misses: 50,
  keyspace: { db0: { keys: 142, expires: 38 } },
};

export const MOCK_REDIS_KEYS: RedisKeysResponse = {
  count: 2,
  keys: [
    { key: "celery-task-meta-abc123", type: "string", ttl: 86400, size_bytes: 240 },
    { key: "_kombu.binding.celery", type: "string", ttl: -1, size_bytes: 120 },
  ],
};

export const MOCK_REDIS_KEY_VALUE: RedisKeyValue = {
  type: "string",
  value: '{"status": "SUCCESS", "result": 42}',
};

export const MOCK_COMPANY: Company = {
  id: 1,
  symbol: "AAPL",
  name: "Apple Inc.",
  exchange: "NASDAQ",
  exchange_display: "NASDAQ",
  currency: "USD",
  currency_display: "US Dollar",
  is_bootstrapped: true,
  sector: 1,
  sector_name: "Technology",
  industry: 1,
  industry_name: "Consumer Electronics",
  market_cap: 3_000_000_000_000,
  trailing_pe: 28.5,
  profit_margins: 0.253,
  dividend_yield: 0.005,
  address: "One Apple Park Way",
  city: "Cupertino",
  state: "CA",
  zip_code: "95014",
  country: "United States",
  phone: "408-996-1010",
  website: "https://www.apple.com",
  ir_website: "https://investor.apple.com",
  description:
    "Apple Inc. designs, manufactures, and markets smartphones, personal computers, tablets, wearables, and accessories worldwide.",
  full_time_employees: 164000,
  officers: [
    {
      name: "Timothy D. Cook",
      title: "CEO & Director",
      age: 62,
      yearBorn: 1960,
      fiscalYear: 2023,
      totalPay: 63200000,
      exercisedValue: null,
      unexercisedValue: null,
    },
  ],
};

export const MOCK_PAGINATED_COMPANIES: PaginatedResponse<Company> = {
  count: 1,
  next: null,
  previous: null,
  results: [MOCK_COMPANY],
};

export const MOCK_TASK_RESULT: TaskResult = {
  task_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  task_name: "apps.companies.tasks.sync_company_profiles",
  periodic_task_name: "yfinance-sync-company-profiles-daily",
  status: "SUCCESS",
  result: '{"created": 1, "synced": 5, "failed": 0}',
  date_created: "2026-05-28T10:00:00Z",
  date_started: "2026-05-28T10:00:01Z",
  date_done: "2026-05-28T10:00:03Z",
  traceback: null,
  task_args: "[]",
  task_kwargs: "{}",
  worker: "celery@prod",
};

export const MOCK_FAILED_TASK_RESULT: TaskResult = {
  ...MOCK_TASK_RESULT,
  task_id: "ffffffff-0000-0000-0000-000000000001",
  status: "FAILURE",
  result: null,
  traceback: "Traceback (most recent call last):\n  File ...\nException: boom",
};

export const MOCK_PAGINATED_TASK_RESULTS = {
  count: 2,
  next: null,
  previous: null,
  results: [MOCK_TASK_RESULT, MOCK_FAILED_TASK_RESULT],
};

export const MOCK_PERIODIC_TASK: PeriodicTask = {
  id: 1,
  name: "yfinance-sync-company-profiles-daily",
  task: "apps.companies.tasks.sync_company_profiles",
  enabled: true,
  interval_display: "every 24 hours",
  last_run_at: "2026-05-28T00:00:00Z",
  next_run_at: "2026-05-29T00:00:00Z",
  total_run_count: 42,
  date_changed: "2026-05-28T00:00:00Z",
};

export const MOCK_SNAPSHOT: CompanySnapshot = {
  id: 1,
  company: 1,
  fetched_at: "2026-05-28T10:00:00Z",
  market_cap: 3000000000000,
  trailing_pe: 28.5,
  forward_pe: 25.1,
  price_to_book: 45.2,
  debt_to_equity: 1.8,
  return_on_equity: 1.47,
  profit_margins: 0.253,
  dividend_yield: 0.005,
  trailing_eps: 6.57,
  forward_eps: 7.21,
  beta: 1.24,
  fifty_two_week_high: 199.62,
  fifty_two_week_low: 164.08,
  week52_change: 0.153,
  sandp52_week_change: 0.272,
  average_volume: 55920000,
  shares_outstanding: 15400000000,
  float_shares: 15390000000,
  enterprise_value: 2990000000000,
  enterprise_to_revenue: 7.62,
  enterprise_to_ebitda: 22.1,
  peg_ratio: 2.8,
  trailing_peg_ratio: null,
  price_to_sales: 7.6,
  payout_ratio: 0.155,
  book_value: 4.2,
  fifty_day_average: 189.3,
  two_hundred_day_average: 183.1,
  revenue_growth: 0.051,
  earnings_growth: 0.11,
  earnings_quarterly_growth: 0.08,
  gross_margins: 0.454,
  operating_margins: 0.313,
  ebitda_margins: 0.338,
  current_ratio: 0.99,
  quick_ratio: 0.94,
  return_on_assets: 0.22,
  ebitda: 130000000000,
  total_cash: 67000000000,
  total_cash_per_share: 4.35,
  free_cashflow: 105000000000,
  operating_cashflow: 118000000000,
  net_income_to_common: 97000000000,
  revenue_per_share: 25.5,
  held_pct_institutions: 0.607,
  held_pct_insiders: 0.027,
  dividend_rate: 1.0,
  ex_dividend_date: "2026-02-07",
  five_year_avg_dividend_yield: 0.68,
  trailing_annual_dividend_rate: 1.0,
  last_dividend_value: 0.25,
  last_dividend_date: "2026-02-13",
  last_fiscal_year_end: "2025-09-27",
  next_fiscal_year_end: "2026-09-26",
  most_recent_quarter: "2025-12-28",
  audit_risk: 5,
  board_risk: 3,
  compensation_risk: 6,
  shareholder_rights_risk: 7,
  overall_risk: 5,
  recommendation_mean: 1.8,
  recommendation_key: "buy",
  num_analyst_opinions: 38,
  target_high_price: 230.0,
  target_low_price: 158.0,
  target_mean_price: 206.0,
  target_median_price: 210.0,
  recommendations_breakdown: [
    { period: "0m", strongBuy: 14, buy: 18, hold: 6, sell: 0, strongSell: 0 },
    { period: "-1m", strongBuy: 13, buy: 17, hold: 7, sell: 1, strongSell: 0 },
    { period: "-2m", strongBuy: 12, buy: 16, hold: 8, sell: 1, strongSell: 0 },
    { period: "-3m", strongBuy: 11, buy: 17, hold: 7, sell: 1, strongSell: 1 },
  ],
  last_split_factor: "4:1",
  last_split_date: "2020-08-31",
  raw: {},
};

export const MOCK_PAGINATED_SNAPSHOTS: PaginatedResponse<CompanySnapshot> = {
  count: 1,
  next: null,
  previous: null,
  results: [MOCK_SNAPSHOT],
};

export const MOCK_FINANCIAL: FinancialStatement = {
  id: 1,
  company: 1,
  statement_type: "income",
  period: "annual",
  period_end: "2023-12-31",
  metric: "Total Revenue",
  value: 394328000000,
};

export const MOCK_PAGINATED_FINANCIALS: PaginatedResponse<FinancialStatement> = {
  count: 1,
  next: null,
  previous: null,
  results: [MOCK_FINANCIAL],
};

export const MOCK_PRICE_BAR: PriceBar = {
  id: 1,
  company: 1,
  date: "2026-05-28",
  open: "189.50",
  high: "191.20",
  low: "188.80",
  close: "190.75",
  volume: 52000000,
};

export const MOCK_PAGINATED_PRICES: PaginatedResponse<PriceBar> = {
  count: 1,
  next: null,
  previous: null,
  results: [MOCK_PRICE_BAR],
};

export const MOCK_DIVIDEND: Dividend = {
  id: 1,
  company: 1,
  date: "2026-03-01",
  amount: "0.2500",
};

export const MOCK_PAGINATED_DIVIDENDS: PaginatedResponse<Dividend> = {
  count: 1,
  next: null,
  previous: null,
  results: [MOCK_DIVIDEND],
};

export const MOCK_HEALTH = {
  version: "v0.1.0",
  db: true,
  redis: true,
  celery: true,
  beat: true,
  ollama: true,
};

export const MOCK_SECTOR: Sector = {
  id: 1,
  name: "Technology",
  description: "Companies in the technology space",
  company_count: 5,
  industry_count: 2,
};

export const MOCK_PAGINATED_SECTORS: PaginatedResponse<Sector> = {
  count: 1,
  next: null,
  previous: null,
  results: [MOCK_SECTOR],
};

export const MOCK_INDUSTRY: Industry = {
  id: 1,
  name: "Consumer Electronics",
  sector: 1,
  sector_name: "Technology",
  company_count: 3,
  total_market_cap: 1_500_000_000,
};

export const MOCK_PAGINATED_INDUSTRIES: PaginatedResponse<Industry> = {
  count: 1,
  next: null,
  previous: null,
  results: [MOCK_INDUSTRY],
};

export const MOCK_MARKET_HIERARCHY_COUNT = [
  {
    name: "Technology",
    value: 5,
    company_count: 5,
    market_cap: 2_000_000_000,
    children: [
      { name: "Consumer Electronics", value: 3, company_count: 3, market_cap: 1_500_000_000 },
      { name: "Other", value: 2, company_count: 2, market_cap: 500_000_000 },
    ],
  },
];

export const MOCK_MARKET_HIERARCHY_MC = [
  {
    name: "Technology",
    value: 2_000_000_000,
    company_count: 5,
    market_cap: 2_000_000_000,
    children: [
      { name: "Consumer Electronics", value: 1_500_000_000, company_count: 3, market_cap: 1_500_000_000 },
      { name: "Other", value: 500_000_000, company_count: 2, market_cap: 500_000_000 },
    ],
  },
];

export const MOCK_MARKET_HIERARCHY = MOCK_MARKET_HIERARCHY_COUNT;

export const MOCK_PIVOTED_FINANCIALS = {
  dates: ["2023-12-31", "2022-12-31"],
  rows: [
    { metric: "Total Revenue", values: [394328000000, 365817000000] },
    { metric: "Net Income", values: [96995000000, 99803000000] },
  ],
};

export const MOCK_SHORT_INTEREST: ShortInterest = {
  id: "si-uuid-1",
  company: 1,
  fetched_at: "2026-05-28T10:00:00Z",
  date_short_interest: "2026-05-15",
  shares_short: 103000000,
  shares_short_prior_month: 98000000,
  short_ratio: 1.84,
  short_pct_of_float: 0.0067,
  shares_pct_shares_out: 0.0067,
};

export const MOCK_PAGINATED_SHORT_INTEREST: PaginatedResponse<ShortInterest> = {
  count: 1,
  next: null,
  previous: null,
  results: [MOCK_SHORT_INTEREST],
};

export const MOCK_INSTITUTIONAL_HOLDERS: InstitutionalHolderSnapshot = {
  id: "ih-uuid-1",
  company: 1,
  fetched_at: "2026-05-28T10:00:00Z",
  holders: [
    { holder: "Vanguard Group Inc", shares: 1280000000, date_reported: "2026-03-31", pct_out: 0.0831, value: 242000000000 },
    { holder: "BlackRock Inc.", shares: 1050000000, date_reported: "2026-03-31", pct_out: 0.0682, value: 199000000000 },
  ],
};

export const MOCK_EARNINGS_DATE: EarningsDate = {
  id: "ed-uuid-1",
  company: 1,
  earnings_date: "2026-07-31",
  eps_estimate: 1.42,
  reported_eps: null,
  surprise_pct: null,
  is_upcoming: true,
};

export const MOCK_PAST_EARNINGS_DATE: EarningsDate = {
  id: "ed-uuid-2",
  company: 1,
  earnings_date: "2026-05-01",
  eps_estimate: 1.61,
  reported_eps: 1.65,
  surprise_pct: 2.48,
  is_upcoming: false,
};

export const MOCK_PAGINATED_EARNINGS: PaginatedResponse<EarningsDate> = {
  count: 2,
  next: null,
  previous: null,
  results: [MOCK_EARNINGS_DATE, MOCK_PAST_EARNINGS_DATE],
};

export const MOCK_OPTIONS_EXPIRY: OptionsExpiry = {
  id: "oe-uuid-1",
  expiry_date: "2026-06-20",
  fetched_at: "2026-05-28T10:00:00Z",
};

export const MOCK_PAGINATED_OPTIONS_EXPIRIES: PaginatedResponse<OptionsExpiry> = {
  count: 1,
  next: null,
  previous: null,
  results: [MOCK_OPTIONS_EXPIRY],
};

export const MOCK_SUMMARY: CompanySummary = {
  id: 1,
  generated_at: "2025-06-01T06:00:00Z",
  model_name: "llama3.2:3b",
  verdict: "buy",
  summary: "Strong fundamentals and solid revenue growth.\n\nVERDICT: BUY",
};

export const MOCK_SYNC_STATUS: SyncStatus = {
  profile: "2026-06-01T10:00:00Z",
  prices: "2026-06-01",
  snapshot: "2026-06-01T10:00:00Z",
  financials: "2026-05-15T08:00:00Z",
  dividends: "2026-05-20T09:00:00Z",
  short_interest: "2026-05-28T10:00:00Z",
  institutional: "2026-05-01T10:00:00Z",
  earnings: "2026-05-28T10:00:00Z",
  options: "2026-05-28T10:00:00Z",
};

export const MOCK_OPTIONS_CHAIN: OptionsChain = {
  id: "oc-uuid-1",
  company: 1,
  expiry_date: "2026-06-20",
  fetched_at: "2026-05-28T10:00:00Z",
  calls: [
    {
      id: "contract-1",
      option_type: "call",
      contract_symbol: "AAPL260620C00190000",
      strike: "190.00",
      last_price: "4.25",
      bid: "4.20",
      ask: "4.30",
      volume: 1200,
      open_interest: 8500,
      implied_volatility: 0.28,
      in_the_money: true,
    },
  ],
  puts: [
    {
      id: "contract-2",
      option_type: "put",
      contract_symbol: "AAPL260620P00185000",
      strike: "185.00",
      last_price: "2.10",
      bid: "2.05",
      ask: "2.15",
      volume: 650,
      open_interest: 4200,
      implied_volatility: 0.31,
      in_the_money: false,
    },
  ],
};

const ZERO_BUCKETS = { lt_1h: 0, h1_6: 0, h6_24: 0, d1_7: 0, d7_30: 0, gt_30d: 0, never: 1 };

export const MOCK_GLOBAL_SYNC_FRESHNESS: GlobalSyncFreshness = {
  total_companies: 2,
  data_types: [
    { label: "Prices", buckets: { ...ZERO_BUCKETS, d1_7: 2, never: 0 } },
    { label: "Snapshot", buckets: { ...ZERO_BUCKETS, d1_7: 2, never: 0 } },
  ],
};

export const MOCK_SYNC_FRESHNESS_MATRIX: SyncFreshnessMatrix = {
  total_companies: 2,
  symbols: ["AAPL", "MSFT"],
  data_types: [
    { label: "Prices", buckets: [3, 3] },
    { label: "Snapshot", buckets: [3, 6] },
  ],
};

const BASE = "http://localhost:8004";

export const handlers: RequestHandler[] = [
  http.get(`${BASE}/api/health/`, () => HttpResponse.json(MOCK_HEALTH)),
  http.get(`${BASE}/api/companies/sectors/`, () => HttpResponse.json(MOCK_PAGINATED_SECTORS)),
  http.get(`${BASE}/api/companies/industries/`, () => HttpResponse.json(MOCK_PAGINATED_INDUSTRIES)),
  http.get(`${BASE}/api/companies/market-hierarchy/`, ({ request }) => {
    const metric = new URL(request.url).searchParams.get("metric");
    return HttpResponse.json(
      metric === "market_cap" ? MOCK_MARKET_HIERARCHY_MC : MOCK_MARKET_HIERARCHY_COUNT,
    );
  }),
  http.get(`${BASE}/api/companies/sync-freshness/matrix/`, () =>
    HttpResponse.json(MOCK_SYNC_FRESHNESS_MATRIX),
  ),
  http.get(`${BASE}/api/companies/sync-freshness/`, () => HttpResponse.json(MOCK_GLOBAL_SYNC_FRESHNESS)),
  http.get(`${BASE}/api/companies/`, () => HttpResponse.json(MOCK_PAGINATED_COMPANIES)),
  http.get(`${BASE}/api/companies/:id/snapshots/`, () => HttpResponse.json(MOCK_PAGINATED_SNAPSHOTS)),
  http.get(`${BASE}/api/companies/:id/financials/pivoted/`, () =>
    HttpResponse.json(MOCK_PIVOTED_FINANCIALS),
  ),
  http.get(`${BASE}/api/companies/:id/financials/`, () => HttpResponse.json(MOCK_PAGINATED_FINANCIALS)),
  http.get(`${BASE}/api/companies/:id/prices/`, () => HttpResponse.json(MOCK_PAGINATED_PRICES)),
  http.get(`${BASE}/api/companies/:id/dividends/`, () => HttpResponse.json(MOCK_PAGINATED_DIVIDENDS)),
  http.get(`${BASE}/api/companies/:id/short-interest/`, () =>
    HttpResponse.json(MOCK_PAGINATED_SHORT_INTEREST),
  ),
  http.get(`${BASE}/api/companies/:id/institutional-holders/`, () =>
    HttpResponse.json(MOCK_INSTITUTIONAL_HOLDERS),
  ),
  http.get(`${BASE}/api/companies/:id/earnings-dates/`, () =>
    HttpResponse.json(MOCK_PAGINATED_EARNINGS),
  ),
  http.get(`${BASE}/api/companies/:id/options/`, () =>
    HttpResponse.json(MOCK_PAGINATED_OPTIONS_EXPIRIES),
  ),
  http.get(`${BASE}/api/companies/:id/options/:expiryDate/`, () =>
    HttpResponse.json(MOCK_OPTIONS_CHAIN),
  ),
  http.get(`${BASE}/api/companies/:id/`, () => HttpResponse.json(MOCK_COMPANY)),
  http.get(`${BASE}/api/companies/:id/sync-status/`, () => HttpResponse.json(MOCK_SYNC_STATUS)),
  http.get(`${BASE}/api/companies/:symbol/summaries/latest/`, () =>
    HttpResponse.json(MOCK_SUMMARY),
  ),
  http.get(`${BASE}/api/companies/:symbol/summaries/`, () =>
    HttpResponse.json({ count: 1, next: null, previous: null, results: [MOCK_SUMMARY] }),
  ),
  http.post(`${BASE}/api/companies/:id/sync/:dataType/`, () =>
    HttpResponse.json({ task_id: "test-task-uuid", status: "queued" }, { status: 202 }),
  ),
  http.post(`${BASE}/api/companies/:symbol/summaries/generate/`, () =>
    HttpResponse.json({ task_id: "summary-task-uuid", status: "queued" }, { status: 202 }),
  ),
  http.post(`${BASE}/api/companies/yf/sync/:symbol/`, () => HttpResponse.json(MOCK_COMPANY)),
  http.get(`${BASE}/api/tasks/results/`, () =>
    HttpResponse.json(MOCK_PAGINATED_TASK_RESULTS),
  ),
  http.get(`${BASE}/api/tasks/results/:taskId/`, () =>
    HttpResponse.json(MOCK_TASK_RESULT),
  ),
  http.get(`${BASE}/api/tasks/schedules/`, () =>
    HttpResponse.json([MOCK_PERIODIC_TASK]),
  ),
  http.patch(`${BASE}/api/tasks/schedules/:id/`, async ({ request }) => {
    const body = await request.json() as { enabled: boolean };
    return HttpResponse.json({ ...MOCK_PERIODIC_TASK, enabled: body.enabled });
  }),
  http.post(`${BASE}/api/tasks/schedules/:id/trigger/`, () =>
    HttpResponse.json({ task_id: "new-task-uuid" }, { status: 202 }),
  ),
  http.get(`${BASE}/api/redis/info/`, () => HttpResponse.json(MOCK_REDIS_INFO)),
  http.get(`${BASE}/api/redis/keys/`, () => HttpResponse.json(MOCK_REDIS_KEYS)),
  http.get(`${BASE}/api/redis/keys/:key/value/`, () => HttpResponse.json(MOCK_REDIS_KEY_VALUE)),
  http.get(`${BASE}/api/llm/models/`, () => HttpResponse.json(MOCK_LLM_MODELS)),
  http.get(`${BASE}/api/llm/settings/`, () => HttpResponse.json(MOCK_LLM_SETTINGS)),
  http.post(`${BASE}/api/llm/chat/`, () => HttpResponse.json(MOCK_LLM_CHAT_RESPONSE)),
  http.post(`${BASE}/api/llm/summarise/`, () => HttpResponse.json(MOCK_LLM_SUMMARISE_RESPONSE)),
  http.post(`${BASE}/api/llm/analyse/`, () => HttpResponse.json(MOCK_LLM_ANALYSE_RESPONSE)),
  http.get(`${BASE}/api/llm/chain/`, () =>
    HttpResponse.json({ count: 1, next: null, previous: null, results: [MOCK_CHAIN_RUN_SUMMARY] }),
  ),
  http.get(`${BASE}/api/llm/chain/:id/`, () => HttpResponse.json(MOCK_CHAIN_RUN_DETAIL)),
  // Other workflow history endpoints default to empty so the unified history
  // fetch (fetchAllRuns) resolves cleanly; individual tests override as needed.
  ...["route", "parallel", "react", "evaluate", "plan", "orchestrate", "multiagent", "dag", "autonomous"].map(
    (t) =>
      http.get(`${BASE}/api/llm/${t}/history/`, () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
  ),
  // Browser agent (/browse). Its history is separate from the Agents feed above.
  http.get(`${BASE}/api/llm/browser/history/`, () =>
    HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
  ),
  // Chat agent (/chat). Sessions are a separate resource from run history: a conversation
  // is not a workflow, so it has no WorkflowSpec and no /history/ endpoint.
  http.get(`${BASE}/api/llm/chat/sessions/`, () =>
    HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
  ),
  http.get(`${BASE}/api/llm/chat/sessions/:id/`, () => new HttpResponse(null, { status: 404 })),
  http.get(`${BASE}/api/llm/chat-agent/history/`, () =>
    HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
  ),
];
