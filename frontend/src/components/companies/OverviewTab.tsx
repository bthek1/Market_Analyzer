import { useState } from "react";
import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts";
import type { Company, CompanySnapshot } from "@/types/companies";
import { buildRadarOption } from "./OverviewTab.chartOptions";
import { SyncPanel } from "@/components/companies/SyncPanel";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

// ---------------------------------------------------------------------------
// Price target range bar (CSS)
// ---------------------------------------------------------------------------

interface RangeBarProps {
  min: number;
  max: number;
  markers: { label: string; value: number; color: string }[];
  title: string;
}

function RangeBar({ min, max, markers, title }: RangeBarProps) {
  const range = max - min;
  if (range <= 0) return null;
  const pct = (v: number) => Math.min(100, Math.max(0, ((v - min) / range) * 100));
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground uppercase tracking-wide">{title}</p>
      <div className="relative h-8 mx-2">
        <div className="absolute top-3 inset-x-0 h-1.5 bg-muted rounded-full" />
        {markers.map(({ label, value, color }) => (
          <div
            key={label}
            className="absolute flex flex-col items-center"
            style={{ left: `${pct(value)}%`, transform: "translateX(-50%)", top: 0 }}
          >
            <div className="w-0.5 h-3" style={{ backgroundColor: color }} />
            <div
              className="w-1.5 h-1.5 rounded-full mt-0.5"
              style={{ backgroundColor: color }}
            />
            <span className="text-[10px] mt-0.5 font-medium" style={{ color }}>
              {label}
            </span>
          </div>
        ))}
      </div>
      <div className="flex justify-between text-xs text-muted-foreground px-2">
        <span>${min.toFixed(0)}</span>
        <span>${max.toFixed(0)}</span>
      </div>
    </div>
  );
}

function PriceTargetBar({ s }: { s: CompanySnapshot }) {
  if (s.target_low_price === null || s.target_high_price === null) return null;
  const markers = [
    { label: "Low", value: s.target_low_price, color: "#ef4444" },
    ...(s.target_mean_price !== null ? [{ label: "Mean", value: s.target_mean_price, color: "#6366f1" }] : []),
    ...(s.target_median_price !== null ? [{ label: "Med", value: s.target_median_price, color: "#0ea5e9" }] : []),
    { label: "High", value: s.target_high_price, color: "#16a34a" },
  ];
  return (
    <RangeBar
      min={s.target_low_price}
      max={s.target_high_price}
      markers={markers}
      title="Analyst Price Target Range"
    />
  );
}

function FiftyTwoWeekBar({ s }: { s: CompanySnapshot }) {
  if (s.fifty_two_week_low === null || s.fifty_two_week_high === null) return null;
  const markers = [
    { label: "52W Low", value: s.fifty_two_week_low, color: "#ef4444" },
    ...(s.fifty_day_average !== null ? [{ label: "50D MA", value: s.fifty_day_average, color: "#f59e0b" }] : []),
    ...(s.two_hundred_day_average !== null ? [{ label: "200D MA", value: s.two_hundred_day_average, color: "#6366f1" }] : []),
    { label: "52W High", value: s.fifty_two_week_high, color: "#16a34a" },
  ];
  return (
    <RangeBar
      min={s.fifty_two_week_low}
      max={s.fifty_two_week_high}
      markers={markers}
      title="52-Week Price Range"
    />
  );
}

function KeyMetricsRadar({ s }: { s: CompanySnapshot }) {
  const option = buildRadarOption(s);
  if (!option) return null;
  return (
    <div>
      <p className="text-xs text-muted-foreground uppercase tracking-wide mb-1">
        Key Metrics (normalised vs benchmarks)
      </p>
      <ReactECharts option={option} style={{ height: 260 }} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

function fmt(value: number | null, type: "number" | "percent" | "currency" | "compact" = "number"): string {
  if (value === null || value === undefined) return "—";
  if (type === "percent") return `${(value * 100).toFixed(2)}%`;
  if (type === "currency")
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      notation: "compact",
      maximumFractionDigits: 2,
    }).format(value);
  if (type === "compact")
    return new Intl.NumberFormat("en-US", {
      notation: "compact",
      maximumFractionDigits: 2,
    }).format(value);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
}

function fmtDate(value: string | null): string {
  if (!value) return "—";
  return value;
}

// ---------------------------------------------------------------------------
// StatCard
// ---------------------------------------------------------------------------

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardHeader className="pb-1">
        <CardTitle className="text-xs uppercase tracking-wide text-muted-foreground font-medium">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-base font-semibold">{value}</p>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// StatGroup
// ---------------------------------------------------------------------------

interface StatGroupProps {
  title: string;
  items: { label: string; value: string }[];
  cols?: string;
}

function StatGroup({ title, items, cols = "grid-cols-2 md:grid-cols-4" }: StatGroupProps) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">{title}</h3>
      <div className={`grid ${cols} gap-3`}>
        {items.map(({ label, value }) => (
          <StatCard key={label} label={label} value={value} />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Risk score bar (1–10)
// ---------------------------------------------------------------------------

function RiskBar({ label, score }: { label: string; score: number | null }) {
  const val = score ?? 0;
  const colour =
    val <= 3 ? "bg-green-500" : val <= 6 ? "bg-yellow-400" : "bg-red-500";
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{label}</span>
        <span>{score ?? "—"} / 10</span>
      </div>
      <div className="h-1.5 rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full ${colour}`}
          style={{ width: `${(val / 10) * 100}%` }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Analyst consensus chart (stacked bar — 4 months)
// ---------------------------------------------------------------------------

function AnalystChart({ breakdown }: { breakdown: CompanySnapshot["recommendations_breakdown"] }) {
  if (!breakdown || breakdown.length === 0) return null;
  const periods = [...breakdown].reverse();
  const option: EChartsOption = {
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { data: ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"], bottom: 0 },
    grid: { left: 40, right: 16, top: 8, bottom: 60 },
    xAxis: { type: "category", data: periods.map((p) => p.period) },
    yAxis: { type: "value" },
    series: [
      { name: "Strong Buy", type: "bar", stack: "total", data: periods.map((p) => p.strongBuy), color: "#16a34a" },
      { name: "Buy", type: "bar", stack: "total", data: periods.map((p) => p.buy), color: "#4ade80" },
      { name: "Hold", type: "bar", stack: "total", data: periods.map((p) => p.hold), color: "#facc15" },
      { name: "Sell", type: "bar", stack: "total", data: periods.map((p) => p.sell), color: "#f97316" },
      { name: "Strong Sell", type: "bar", stack: "total", data: periods.map((p) => p.strongSell), color: "#ef4444" },
    ],
  };
  return <ReactECharts option={option} style={{ height: 200 }} />;
}

// ---------------------------------------------------------------------------
// Officers table
// ---------------------------------------------------------------------------

function OfficersTable({ officers }: { officers: Company["officers"] }) {
  if (!officers || officers.length === 0) return null;
  return (
    <div className="rounded-md border overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Title</TableHead>
            <TableHead className="text-right">Total Pay</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {officers.map((o, i) => (
            <TableRow key={i}>
              <TableCell className="font-medium">{o.name}</TableCell>
              <TableCell className="text-muted-foreground text-sm">{o.title}</TableCell>
              <TableCell className="text-right font-mono text-sm">
                {o.totalPay
                  ? new Intl.NumberFormat("en-US", {
                      style: "currency",
                      currency: "USD",
                      notation: "compact",
                      maximumFractionDigits: 1,
                    }).format(o.totalPay)
                  : "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// About section
// ---------------------------------------------------------------------------

const DESCRIPTION_LIMIT = 400;

function AboutSection({ company }: { company: Company }) {
  const [expanded, setExpanded] = useState(false);
  const desc = company.description || "";
  const truncated = desc.length > DESCRIPTION_LIMIT && !expanded;

  return (
    <div className="space-y-4">
      {desc && (
        <div>
          <p className="text-sm text-muted-foreground leading-relaxed">
            {truncated ? desc.slice(0, DESCRIPTION_LIMIT) + "…" : desc}
          </p>
          {desc.length > DESCRIPTION_LIMIT && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="text-xs text-primary mt-1 hover:underline"
            >
              {expanded ? "Show less" : "Show more"}
            </button>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-2 text-sm">
        {company.full_time_employees && (
          <div>
            <span className="text-muted-foreground">Employees</span>
            <p className="font-medium">
              {new Intl.NumberFormat("en-US").format(company.full_time_employees)}
            </p>
          </div>
        )}
        {(company.city || company.country) && (
          <div>
            <span className="text-muted-foreground">Headquarters</span>
            <p className="font-medium">
              {[company.city, company.state, company.country].filter(Boolean).join(", ")}
            </p>
          </div>
        )}
        {company.phone && (
          <div>
            <span className="text-muted-foreground">Phone</span>
            <p className="font-medium">{company.phone}</p>
          </div>
        )}
        {company.website && (
          <div>
            <span className="text-muted-foreground">Website</span>
            <a
              href={company.website}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-primary hover:underline"
            >
              {company.website.replace(/^https?:\/\//, "")}
            </a>
          </div>
        )}
        {company.ir_website && (
          <div>
            <span className="text-muted-foreground">Investor Relations</span>
            <a
              href={company.ir_website}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-primary hover:underline"
            >
              IR Website
            </a>
          </div>
        )}
      </div>

      {company.officers && company.officers.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">Leadership</h3>
          <OfficersTable officers={company.officers} />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main OverviewTab
// ---------------------------------------------------------------------------

interface OverviewTabProps {
  company: Company;
  snapshot: CompanySnapshot | null;
}

export function OverviewTab({ company, snapshot: s }: OverviewTabProps) {
  return (
    <div className="space-y-8">
      {/* Sync controls */}
      <div className="flex flex-wrap items-center gap-6 border-b pb-3">
        <SyncPanel companyId={company.id} dataType="profile" label="Profile" />
        <SyncPanel companyId={company.id} dataType="snapshot" label="Snapshot" />
      </div>

      {/* About */}
      <section className="space-y-3">
        <h2 className="text-base font-semibold tracking-tight">About</h2>
        <AboutSection company={company} />
      </section>

      {/* Profile */}
      <section className="space-y-3">
        <h2 className="text-base font-semibold tracking-tight">Profile</h2>
        <StatGroup
          title=""
          items={[
            { label: "Exchange", value: company.exchange_display || "—" },
            { label: "Currency", value: company.currency_display || "—" },
            { label: "Sector", value: company.sector_name || "—" },
            { label: "Industry", value: company.industry_name || "—" },
          ]}
        />
      </section>

      {!s && (
        <p className="text-sm text-muted-foreground">No snapshot data available.</p>
      )}

      {s && (
        <>
          {/* Valuation */}
          <section className="space-y-4">
            <h2 className="text-base font-semibold tracking-tight">Valuation</h2>
            <StatGroup
              title="Market"
              items={[
                { label: "Market Cap", value: fmt(s.market_cap, "compact") },
                { label: "Enterprise Value", value: fmt(s.enterprise_value, "compact") },
                { label: "Trailing P/E", value: fmt(s.trailing_pe) },
                { label: "Forward P/E", value: fmt(s.forward_pe) },
                { label: "PEG Ratio", value: fmt(s.peg_ratio) },
                { label: "Price / Book", value: fmt(s.price_to_book) },
                { label: "Price / Sales", value: fmt(s.price_to_sales) },
                { label: "EV / Revenue", value: fmt(s.enterprise_to_revenue) },
                { label: "EV / EBITDA", value: fmt(s.enterprise_to_ebitda) },
              ]}
              cols="grid-cols-2 md:grid-cols-3 lg:grid-cols-4"
            />
            <StatGroup
              title="Per Share"
              items={[
                { label: "Trailing EPS", value: fmt(s.trailing_eps) },
                { label: "Forward EPS", value: fmt(s.forward_eps) },
                { label: "Book Value / Share", value: fmt(s.book_value) },
                { label: "Cash / Share", value: fmt(s.total_cash_per_share) },
                { label: "Revenue / Share", value: fmt(s.revenue_per_share) },
              ]}
            />
          </section>

          {/* Key metrics radar */}
          <section className="space-y-4">
            <h2 className="text-base font-semibold tracking-tight">Performance Overview</h2>
            <KeyMetricsRadar s={s} />
          </section>

          {/* Growth & Margins */}
          <section className="space-y-4">
            <h2 className="text-base font-semibold tracking-tight">Growth & Margins</h2>
            <StatGroup
              title="Growth"
              items={[
                { label: "Revenue Growth (YoY)", value: fmt(s.revenue_growth, "percent") },
                { label: "Earnings Growth", value: fmt(s.earnings_growth, "percent") },
                { label: "Earnings (QoQ)", value: fmt(s.earnings_quarterly_growth, "percent") },
              ]}
            />
            <StatGroup
              title="Margins"
              items={[
                { label: "Gross Margin", value: fmt(s.gross_margins, "percent") },
                { label: "Operating Margin", value: fmt(s.operating_margins, "percent") },
                { label: "EBITDA Margin", value: fmt(s.ebitda_margins, "percent") },
                { label: "Profit Margin", value: fmt(s.profit_margins, "percent") },
              ]}
            />
          </section>

          {/* Balance Sheet */}
          <section className="space-y-4">
            <h2 className="text-base font-semibold tracking-tight">Balance Sheet & Profitability</h2>
            <StatGroup
              title="Ratios"
              items={[
                { label: "Debt / Equity", value: fmt(s.debt_to_equity) },
                { label: "Current Ratio", value: fmt(s.current_ratio) },
                { label: "Quick Ratio", value: fmt(s.quick_ratio) },
                { label: "ROE", value: fmt(s.return_on_equity, "percent") },
                { label: "ROA", value: fmt(s.return_on_assets, "percent") },
                { label: "Payout Ratio", value: fmt(s.payout_ratio, "percent") },
              ]}
            />
            <StatGroup
              title="Cash & Earnings"
              items={[
                { label: "Total Cash", value: fmt(s.total_cash, "compact") },
                { label: "Free Cash Flow", value: fmt(s.free_cashflow, "compact") },
                { label: "Operating Cash Flow", value: fmt(s.operating_cashflow, "compact") },
                { label: "EBITDA", value: fmt(s.ebitda, "compact") },
                { label: "Net Income (Common)", value: fmt(s.net_income_to_common, "compact") },
              ]}
            />
          </section>

          {/* Technical */}
          <section className="space-y-4">
            <h2 className="text-base font-semibold tracking-tight">Technical & Market Data</h2>
            <FiftyTwoWeekBar s={s} />
            <StatGroup
              title=""
              items={[
                { label: "52W High", value: fmt(s.fifty_two_week_high) },
                { label: "52W Low", value: fmt(s.fifty_two_week_low) },
                { label: "52W Change", value: fmt(s.week52_change, "percent") },
                { label: "vs S&P 52W", value: fmt(s.sandp52_week_change, "percent") },
                { label: "50-Day MA", value: fmt(s.fifty_day_average) },
                { label: "200-Day MA", value: fmt(s.two_hundred_day_average) },
                { label: "Beta", value: fmt(s.beta) },
                { label: "Avg Volume", value: fmt(s.average_volume, "compact") },
                { label: "Shares Outstanding", value: fmt(s.shares_outstanding, "compact") },
                { label: "Float Shares", value: fmt(s.float_shares, "compact") },
              ]}
              cols="grid-cols-2 md:grid-cols-5"
            />
          </section>

          {/* Ownership */}
          <section className="space-y-3">
            <h2 className="text-base font-semibold tracking-tight">Ownership</h2>
            <StatGroup
              title=""
              items={[
                { label: "Institutional %", value: fmt(s.held_pct_institutions, "percent") },
                { label: "Insider %", value: fmt(s.held_pct_insiders, "percent") },
              ]}
              cols="grid-cols-2"
            />
          </section>

          {/* Governance Risk */}
          <section className="space-y-3">
            <h2 className="text-base font-semibold tracking-tight">Governance Risk</h2>
            <p className="text-xs text-muted-foreground">Score 1–10; lower is better.</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-3">
                <RiskBar label="Overall Risk" score={s.overall_risk} />
                <RiskBar label="Audit Risk" score={s.audit_risk} />
                <RiskBar label="Board Risk" score={s.board_risk} />
              </div>
              <div className="space-y-3">
                <RiskBar label="Compensation Risk" score={s.compensation_risk} />
                <RiskBar label="Shareholder Rights Risk" score={s.shareholder_rights_risk} />
              </div>
            </div>
          </section>

          {/* Analyst Consensus */}
          <section className="space-y-3">
            <h2 className="text-base font-semibold tracking-tight">Analyst Consensus</h2>
            <div className="flex flex-wrap items-center gap-3 mb-2">
              {s.recommendation_key && (
                <Badge
                  variant="secondary"
                  className={
                    s.recommendation_key === "buy" || s.recommendation_key === "strong_buy"
                      ? "bg-green-100 text-green-800"
                      : s.recommendation_key === "sell" || s.recommendation_key === "strong_sell"
                        ? "bg-red-100 text-red-800"
                        : "bg-yellow-100 text-yellow-800"
                  }
                >
                  {s.recommendation_key.replace("_", " ").toUpperCase()}
                </Badge>
              )}
              {s.recommendation_mean !== null && (
                <span className="text-sm text-muted-foreground">
                  Mean {s.recommendation_mean?.toFixed(2)} / 5
                </span>
              )}
              {s.num_analyst_opinions !== null && (
                <span className="text-sm text-muted-foreground">
                  ({s.num_analyst_opinions} analysts)
                </span>
              )}
            </div>
            <StatGroup
              title="Price Targets"
              items={[
                { label: "Target High", value: fmt(s.target_high_price) },
                { label: "Target Low", value: fmt(s.target_low_price) },
                { label: "Target Mean", value: fmt(s.target_mean_price) },
                { label: "Target Median", value: fmt(s.target_median_price) },
              ]}
            />
            <PriceTargetBar s={s} />
            {s.recommendations_breakdown && s.recommendations_breakdown.length > 0 && (
              <div className="mt-2">
                <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                  Ratings Breakdown
                </h3>
                <AnalystChart breakdown={s.recommendations_breakdown} />
              </div>
            )}
          </section>

          {/* Split & Calendar */}
          <section className="space-y-3">
            <h2 className="text-base font-semibold tracking-tight">Split & Fiscal Calendar</h2>
            <StatGroup
              title=""
              items={[
                { label: "Last Split", value: s.last_split_factor ?? "—" },
                { label: "Split Date", value: fmtDate(s.last_split_date) },
                { label: "Last FY End", value: fmtDate(s.last_fiscal_year_end) },
                { label: "Next FY End", value: fmtDate(s.next_fiscal_year_end) },
                { label: "Most Recent Quarter", value: fmtDate(s.most_recent_quarter) },
              ]}
            />
          </section>
        </>
      )}
    </div>
  );
}
