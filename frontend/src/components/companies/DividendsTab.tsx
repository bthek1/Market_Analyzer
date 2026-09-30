import { useState } from "react";
import ReactECharts from "echarts-for-react";
import { useCompanyDividends } from "@/hooks/useCompanies";
import { SyncPanel } from "@/components/companies/SyncPanel";
import type { CompanySnapshot } from "@/types/companies";
import { buildDividendOption, buildAnnualDividendOption } from "./DividendsTab.chartOptions";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";

function fmt(v: number | null, type: "number" | "percent" | "currency" = "number"): string {
  if (v === null || v === undefined) return "—";
  if (type === "percent") return `${(v * 100).toFixed(2)}%`;
  if (type === "currency")
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 4,
    }).format(v);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(v);
}

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

const PAGE_SIZE = 10;

interface DividendsTabProps {
  companyId: number | string;
  snapshot: CompanySnapshot | null;
}

export function DividendsTab({ companyId, snapshot: s }: DividendsTabProps) {
  const { data, isLoading } = useCompanyDividends(companyId);
  const [page, setPage] = useState(1);
  const dividends = data?.results ?? [];

  const pageStart = (page - 1) * PAGE_SIZE;
  const pageDividends = dividends.slice(pageStart, pageStart + PAGE_SIZE);
  const totalPages = Math.max(1, Math.ceil(dividends.length / PAGE_SIZE));

  const id = Number(companyId);

  return (
    <div className="space-y-8">
      {/* Sync */}
      <div className="border-b pb-3">
        <SyncPanel companyId={id} dataType="dividends" label="Dividends" />
      </div>

      {/* Dividend metrics from snapshot */}
      {s && (
        <section className="space-y-3">
          <h2 className="text-base font-semibold tracking-tight">Dividend Metrics</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard label="Dividend Rate" value={fmt(s.dividend_rate, "currency")} />
            <StatCard label="Dividend Yield" value={fmt(s.dividend_yield, "percent")} />
            <StatCard label="5Y Avg Yield" value={fmt(s.five_year_avg_dividend_yield, "percent")} />
            <StatCard label="Payout Ratio" value={fmt(s.payout_ratio, "percent")} />
            <StatCard label="Trailing Annual Rate" value={fmt(s.trailing_annual_dividend_rate, "currency")} />
            <StatCard label="Last Dividend" value={fmt(s.last_dividend_value, "currency")} />
            <StatCard label="Ex-Dividend Date" value={s.ex_dividend_date ?? "—"} />
            <StatCard label="Last Dividend Date" value={s.last_dividend_date ?? "—"} />
          </div>
        </section>
      )}

      {/* History */}
      <section className="space-y-4">
        <h2 className="text-base font-semibold tracking-tight">Dividend History</h2>
        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {!isLoading && dividends.length === 0 && (
          <p className="text-sm text-muted-foreground">No dividend data available.</p>
        )}
        {!isLoading && dividends.length > 0 && (
          <>
            {buildAnnualDividendOption(dividends, s?.dividend_rate) && (
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wide mb-1">
                  Annual Dividend & YoY Growth
                </p>
                <ReactECharts
                  option={buildAnnualDividendOption(dividends, s?.dividend_rate)!}
                  style={{ height: 220 }}
                />
              </div>
            )}
            {dividends.length >= 2 && (
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wide mb-1">
                  Dividend History
                </p>
                <ReactECharts option={buildDividendOption(dividends)} style={{ height: 200 }} />
              </div>
            )}
            <div className="rounded-md border overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead className="text-right">Amount</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pageDividends.map((d) => (
                    <TableRow key={d.id}>
                      <TableCell className="font-mono text-sm">{d.date}</TableCell>
                      <TableCell className="text-right font-mono text-sm">${d.amount}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {dividends.length > PAGE_SIZE && (
              <div className="flex items-center justify-end gap-3 text-sm">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page === 1}
                  onClick={() => setPage((p) => p - 1)}
                >
                  Prev
                </Button>
                <span className="text-muted-foreground">
                  Page {page} of {totalPages}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </Button>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}
