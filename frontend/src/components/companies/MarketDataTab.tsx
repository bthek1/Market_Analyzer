import { useState } from "react";
import ReactECharts from "echarts-for-react";
import { PriceChart } from "@/components/companies/PriceChart";
import { useCompanyPrices, useShortInterest } from "@/hooks/useCompanies";
import { SyncPanel } from "@/components/companies/SyncPanel";
import type { CompanySnapshot } from "@/types/companies";
import { buildShortInterestOption } from "./MarketDataTab.chartOptions";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const PAGE_SIZE = 5;

function fmt(v: number | null, type: "number" | "percent" | "compact" = "number"): string {
  if (v === null || v === undefined) return "—";
  if (type === "percent") return `${(v * 100).toFixed(2)}%`;
  if (type === "compact")
    return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(v);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(v);
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

interface MarketDataTabProps {
  companyId: number | string;
  snapshot: CompanySnapshot | null;
}

export function MarketDataTab({ companyId, snapshot }: MarketDataTabProps) {
  const [page, setPage] = useState(1);
  const { data: chartData, isLoading } = useCompanyPrices(companyId);
  const { data: pageData } = useCompanyPrices(companyId, {
    ordering: "-date",
    page_size: PAGE_SIZE,
    page,
  });
  const { data: siData } = useShortInterest(companyId);

  const chartBars = chartData?.results ?? [];
  const pageBars = pageData?.results ?? [];
  const totalCount = pageData?.count ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

  const siRecords = siData?.results ?? [];
  const latestSI = siRecords[0] ?? null;

  const maProps = snapshot
    ? {
        fiftyDayAverage: snapshot.fifty_day_average ?? undefined,
        twoHundredDayAverage: snapshot.two_hundred_day_average ?? undefined,
      }
    : {};

  const id = Number(companyId);

  return (
    <div className="space-y-8">
      {/* Sync controls */}
      <div className="flex flex-wrap items-center gap-6 border-b pb-3">
        <SyncPanel companyId={id} dataType="prices" label="Prices" />
        <SyncPanel companyId={id} dataType="short_interest" label="Short Interest" />
      </div>

      {/* Price History */}
      <section className="space-y-4">
        <h2 className="text-base font-semibold tracking-tight">Price History</h2>
        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {!isLoading && chartBars.length === 0 && (
          <p className="text-sm text-muted-foreground">No price history available.</p>
        )}
        {!isLoading && chartBars.length > 0 && (
          <>
            <PriceChart bars={chartBars} {...maProps} />
            <div className="rounded-md border overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead className="text-right">Open</TableHead>
                    <TableHead className="text-right">High</TableHead>
                    <TableHead className="text-right">Low</TableHead>
                    <TableHead className="text-right">Close</TableHead>
                    <TableHead className="text-right">Volume</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pageBars.map((bar) => (
                    <TableRow key={bar.id}>
                      <TableCell className="font-mono text-sm">{bar.date}</TableCell>
                      <TableCell className="text-right font-mono text-sm">{bar.open}</TableCell>
                      <TableCell className="text-right font-mono text-sm">{bar.high}</TableCell>
                      <TableCell className="text-right font-mono text-sm">{bar.low}</TableCell>
                      <TableCell className="text-right font-mono text-sm">{bar.close}</TableCell>
                      <TableCell className="text-right font-mono text-sm">
                        {bar.volume.toLocaleString()}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
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
          </>
        )}
      </section>

      {/* Short Interest */}
      <section className="space-y-4">
        <h2 className="text-base font-semibold tracking-tight">Short Interest</h2>
        {siRecords.length === 0 && (
          <p className="text-sm text-muted-foreground">No short interest data available.</p>
        )}
        {latestSI && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <StatCard label="Shares Short" value={fmt(latestSI.shares_short, "compact")} />
              <StatCard label="Short Ratio (Days)" value={fmt(latestSI.short_ratio)} />
              <StatCard label="Short % of Float" value={fmt(latestSI.short_pct_of_float, "percent")} />
              <StatCard label="% of Shares Out" value={fmt(latestSI.shares_pct_shares_out, "percent")} />
            </div>
            {siRecords.length > 1 && (
              <div className="space-y-4">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">
                  Short Interest Trend
                </p>
                <ReactECharts
                  option={buildShortInterestOption(siRecords)}
                  style={{ height: 200 }}
                />
              </div>
            )}
            {siRecords.length > 1 && (
              <div className="rounded-md border overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Date</TableHead>
                      <TableHead className="text-right">Shares Short</TableHead>
                      <TableHead className="text-right">Short % of Float</TableHead>
                      <TableHead className="text-right">Short Ratio</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {siRecords.slice(0, 6).map((si) => (
                      <TableRow key={si.id}>
                        <TableCell className="font-mono text-sm">{si.date_short_interest ?? "—"}</TableCell>
                        <TableCell className="text-right font-mono text-sm">
                          {fmt(si.shares_short, "compact")}
                        </TableCell>
                        <TableCell className="text-right font-mono text-sm">
                          {fmt(si.short_pct_of_float, "percent")}
                        </TableCell>
                        <TableCell className="text-right font-mono text-sm">
                          {fmt(si.short_ratio)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}
