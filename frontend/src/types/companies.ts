export interface Sector {
  id: number;
  name: string;
  description: string;
  company_count: number;
  industry_count: number;
}

export interface Industry {
  id: number;
  name: string;
  sector: number | null;
  sector_name: string | null;
  company_count: number;
  total_market_cap: number | null;
}

export type Exchange =
  | "NYSE"
  | "NASDAQ"
  | "AMEX"
  | "NYSE_ARCA"
  | "LSE"
  | "ASX"
  | "TSX"
  | "OTHER"
  | "";

export type Currency =
  | "USD"
  | "EUR"
  | "GBP"
  | "AUD"
  | "CAD"
  | "JPY"
  | "CHF"
  | "HKD"
  | "CNY"
  | "OTHER"
  | "";

export interface Officer {
  name: string;
  title: string;
  age: number | null;
  yearBorn: number | null;
  fiscalYear: number | null;
  totalPay: number | null;
  exercisedValue: number | null;
  unexercisedValue: number | null;
}

export interface Company {
  id: number;
  symbol: string;
  name: string;
  exchange: Exchange;
  exchange_display: string;
  currency: Currency;
  currency_display: string;
  is_bootstrapped: boolean;
  sector: number | null;
  sector_name: string | null;
  industry: number | null;
  industry_name: string | null;
  // Latest snapshot metrics (annotated on list endpoint)
  market_cap: number | null;
  trailing_pe: number | null;
  profit_margins: number | null;
  dividend_yield: number | null;
  // Phase 0 profile fields
  address: string;
  city: string;
  state: string;
  zip_code: string;
  country: string;
  phone: string;
  website: string;
  ir_website: string;
  description: string;
  full_time_employees: number | null;
  officers: Officer[];
}

export interface PriceBar {
  id: number;
  company: number;
  date: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: number;
}

export interface CompanySnapshot {
  id: number;
  company: number;
  fetched_at: string;
  // Core valuation
  market_cap: number | null;
  trailing_pe: number | null;
  forward_pe: number | null;
  price_to_book: number | null;
  debt_to_equity: number | null;
  return_on_equity: number | null;
  profit_margins: number | null;
  dividend_yield: number | null;
  trailing_eps: number | null;
  forward_eps: number | null;
  // Phase 1 valuation extensions
  beta: number | null;
  fifty_two_week_high: number | null;
  fifty_two_week_low: number | null;
  week52_change: number | null;
  sandp52_week_change: number | null;
  average_volume: number | null;
  shares_outstanding: number | null;
  float_shares: number | null;
  enterprise_value: number | null;
  enterprise_to_revenue: number | null;
  enterprise_to_ebitda: number | null;
  peg_ratio: number | null;
  trailing_peg_ratio: number | null;
  price_to_sales: number | null;
  payout_ratio: number | null;
  book_value: number | null;
  // Technical
  fifty_day_average: number | null;
  two_hundred_day_average: number | null;
  // Growth
  revenue_growth: number | null;
  earnings_growth: number | null;
  earnings_quarterly_growth: number | null;
  // Margins
  gross_margins: number | null;
  operating_margins: number | null;
  ebitda_margins: number | null;
  // Liquidity
  current_ratio: number | null;
  quick_ratio: number | null;
  // Profitability
  return_on_assets: number | null;
  ebitda: number | null;
  total_cash: number | null;
  total_cash_per_share: number | null;
  free_cashflow: number | null;
  operating_cashflow: number | null;
  net_income_to_common: number | null;
  revenue_per_share: number | null;
  // Ownership
  held_pct_institutions: number | null;
  held_pct_insiders: number | null;
  // Dividend snapshot
  dividend_rate: number | null;
  ex_dividend_date: string | null;
  five_year_avg_dividend_yield: number | null;
  trailing_annual_dividend_rate: number | null;
  last_dividend_value: number | null;
  last_dividend_date: string | null;
  // Fiscal calendar
  last_fiscal_year_end: string | null;
  next_fiscal_year_end: string | null;
  most_recent_quarter: string | null;
  // Governance risk (1-10, lower is better)
  audit_risk: number | null;
  board_risk: number | null;
  compensation_risk: number | null;
  shareholder_rights_risk: number | null;
  overall_risk: number | null;
  // Analyst consensus
  recommendation_mean: number | null;
  recommendation_key: string | null;
  num_analyst_opinions: number | null;
  target_high_price: number | null;
  target_low_price: number | null;
  target_mean_price: number | null;
  target_median_price: number | null;
  recommendations_breakdown: RecommendationPeriod[];
  // Split history
  last_split_factor: string | null;
  last_split_date: string | null;
  raw: Record<string, unknown>;
}

export interface RecommendationPeriod {
  period: string;
  strongBuy: number;
  buy: number;
  hold: number;
  sell: number;
  strongSell: number;
}

export interface FinancialStatement {
  id: number;
  company: number;
  statement_type: "income" | "balance" | "cashflow";
  period: "annual" | "quarterly";
  period_end: string;
  metric: string;
  value: number | null;
}

export interface Dividend {
  id: number;
  company: number;
  date: string;
  amount: string;
}

export interface ShortInterest {
  id: string;
  company: number;
  fetched_at: string;
  date_short_interest: string | null;
  shares_short: number | null;
  shares_short_prior_month: number | null;
  short_ratio: number | null;
  short_pct_of_float: number | null;
  shares_pct_shares_out: number | null;
}

export interface InstitutionalHolder {
  holder: string;
  shares: number;
  date_reported: string;
  pct_out: number;
  value: number;
}

export interface InstitutionalHolderSnapshot {
  id: string;
  company: number;
  fetched_at: string;
  holders: InstitutionalHolder[];
}

export interface EarningsDate {
  id: string;
  company: number;
  earnings_date: string;
  eps_estimate: number | null;
  reported_eps: number | null;
  surprise_pct: number | null;
  is_upcoming: boolean;
}

export interface OptionsExpiry {
  id: string;
  expiry_date: string;
  fetched_at: string;
}

export interface OptionsContract {
  id: string;
  option_type: "call" | "put";
  contract_symbol: string;
  strike: string;
  last_price: string | null;
  bid: string | null;
  ask: string | null;
  volume: number | null;
  open_interest: number | null;
  implied_volatility: number | null;
  in_the_money: boolean | null;
}

export interface OptionsChain {
  id: string;
  company: number;
  expiry_date: string;
  fetched_at: string;
  calls: OptionsContract[];
  puts: OptionsContract[];
}

export type SyncDataType =
  | "profile"
  | "prices"
  | "snapshot"
  | "financials"
  | "dividends"
  | "short_interest"
  | "institutional"
  | "earnings"
  | "options";

export interface SyncStatus {
  profile: string | null;
  prices: string | null;
  snapshot: string | null;
  financials: string | null;
  dividends: string | null;
  short_interest: string | null;
  institutional: string | null;
  earnings: string | null;
  options: string | null;
}

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export type MarketHierarchyMetric = "count" | "market_cap";

export interface ChartNode {
  name: string;
  value: number;
  company_count: number;
  market_cap?: number;
  children?: ChartNode[];
}

export interface PivotedFinancials {
  dates: string[];
  rows: { metric: string; values: (number | null)[] }[];
}

export type SummaryVerdict = "buy" | "hold" | "sell" | "insufficient_data";

export interface CompanySummary {
  id: number;
  generated_at: string;
  model_name: string;
  verdict: SummaryVerdict;
  summary: string;
  /** 0-1, as reported by the model. Absent on rows written before issue #3 Phase 2. */
  confidence?: number | null;
  key_risks?: string[];
  key_drivers?: string[];
  /** The numbers the verdict was based on. `stale_data` lists any failed freshness check. */
  data_snapshot?: Record<string, unknown>;
}
