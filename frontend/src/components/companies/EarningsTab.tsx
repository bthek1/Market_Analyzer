import { useState } from "react";
import ReactECharts from "echarts-for-react";
import { useEarningsDates } from "@/hooks/useCompanies";
import { SyncPanel } from "@/components/companies/SyncPanel";
import { buildSurpriseTrendOption, buildEPSOption } from "./EarningsTab.chartOptions";
import { Badge } from "@/components/ui/badge";
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

function fmt(v: number | null, decimals = 2): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(decimals);
}

const PAGE_SIZE = 10;

interface EarningsTabProps {
  companyId: number | string;
}

export function EarningsTab({ companyId }: EarningsTabProps) {
  const { data, isLoading } = useEarningsDates(companyId);
  const [page, setPage] = useState(1);
  const records = data?.results ?? [];

  const upcoming = records.filter((r) => r.is_upcoming);
  const historical = records.filter((r) => !r.is_upcoming);

  const pageStart = (page - 1) * PAGE_SIZE;
  const pageRecords = records.slice(pageStart, pageStart + PAGE_SIZE);
  const totalPages = Math.max(1, Math.ceil(records.length / PAGE_SIZE));

  const hasEPSData = historical.some((r) => r.reported_eps !== null);
  const surpriseOption = buildSurpriseTrendOption(historical);

  const id = Number(companyId);

  return (
    <div className="space-y-8">
      {/* Sync */}
      <div className="border-b pb-3">
        <SyncPanel companyId={id} dataType="earnings" label="Earnings" />
      </div>

      {/* Upcoming */}
      {upcoming.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-base font-semibold tracking-tight">Upcoming Earnings</h2>
          <div className="flex flex-col gap-3">
            {upcoming.map((e) => (
              <Card key={e.id} className="border-primary/40 bg-primary/5">
                <CardHeader className="pb-1">
                  <CardTitle className="text-sm flex items-center gap-2">
                    {e.earnings_date}
                    <Badge variant="secondary" className="bg-primary/10 text-primary">Upcoming</Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent className="text-sm text-muted-foreground">
                  EPS Estimate: <span className="font-semibold text-foreground">{fmt(e.eps_estimate)}</span>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      )}

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}

      {!isLoading && records.length === 0 && (
        <p className="text-sm text-muted-foreground">No earnings data available.</p>
      )}

      {/* EPS chart */}
      {!isLoading && hasEPSData && (
        <section className="space-y-3">
          <h2 className="text-base font-semibold tracking-tight">EPS History</h2>
          <ReactECharts option={buildEPSOption(historical)} style={{ height: 240 }} />
        </section>
      )}

      {/* EPS surprise % trend */}
      {!isLoading && surpriseOption && (
        <section className="space-y-3">
          <h2 className="text-base font-semibold tracking-tight">EPS Surprise % Trend</h2>
          <ReactECharts option={surpriseOption} style={{ height: 200 }} />
        </section>
      )}

      {/* Full table */}
      {!isLoading && records.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-base font-semibold tracking-tight">Earnings Calendar</h2>
          <div className="rounded-md border overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead className="text-right">EPS Estimate</TableHead>
                  <TableHead className="text-right">Reported EPS</TableHead>
                  <TableHead className="text-right">Surprise %</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pageRecords.map((r) => {
                  const beat =
                    r.reported_eps !== null &&
                    r.eps_estimate !== null &&
                    r.reported_eps >= r.eps_estimate;
                  return (
                    <TableRow key={r.id}>
                      <TableCell className="font-mono text-sm">{r.earnings_date}</TableCell>
                      <TableCell className="text-right font-mono text-sm">{fmt(r.eps_estimate)}</TableCell>
                      <TableCell
                        className={`text-right font-mono text-sm font-medium ${
                          r.reported_eps !== null
                            ? beat
                              ? "text-green-600"
                              : "text-red-500"
                            : ""
                        }`}
                      >
                        {fmt(r.reported_eps)}
                      </TableCell>
                      <TableCell className="text-right font-mono text-sm">
                        {r.surprise_pct !== null ? `${r.surprise_pct.toFixed(2)}%` : "—"}
                      </TableCell>
                      <TableCell>
                        {r.is_upcoming && (
                          <Badge variant="secondary" className="bg-primary/10 text-primary text-xs">
                            Upcoming
                          </Badge>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
          {records.length > PAGE_SIZE && (
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
        </section>
      )}
    </div>
  );
}
