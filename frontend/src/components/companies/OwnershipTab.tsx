import ReactECharts from "echarts-for-react";
import { useInstitutionalHolders } from "@/hooks/useCompanies";
import { SyncPanel } from "@/components/companies/SyncPanel";
import type { CompanySnapshot } from "@/types/companies";
import { buildOwnershipDonutOption, buildTopHoldersOption } from "./OwnershipTab.chartOptions";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

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

interface OwnershipTabProps {
  companyId: number | string;
  snapshot: CompanySnapshot | null;
}

export function OwnershipTab({ companyId, snapshot }: OwnershipTabProps) {
  const { data: holdersSnapshot, isLoading } = useInstitutionalHolders(companyId);
  const id = Number(companyId);

  const holders = holdersSnapshot?.holders ?? [];
  const sorted = [...holders].sort((a, b) => b.pct_out - a.pct_out);

  return (
    <div className="space-y-8">
      {/* Sync */}
      <div className="border-b pb-3">
        <SyncPanel companyId={id} dataType="institutional" label="Institutional Holders" />
      </div>

      {/* Summary percentages + donut */}
      {snapshot && (
        <section className="space-y-3">
          <h2 className="text-base font-semibold tracking-tight">Ownership Summary</h2>
          <div className="grid grid-cols-2 gap-3">
            <StatCard
              label="Institutional Ownership"
              value={fmt(snapshot.held_pct_institutions, "percent")}
            />
            <StatCard
              label="Insider Ownership"
              value={fmt(snapshot.held_pct_insiders, "percent")}
            />
          </div>
          {buildOwnershipDonutOption(snapshot) && (
            <ReactECharts
              option={buildOwnershipDonutOption(snapshot)!}
              style={{ height: 220 }}
            />
          )}
        </section>
      )}

      {/* Institutional holders table */}
      <section className="space-y-3">
        <h2 className="text-base font-semibold tracking-tight">Institutional Holders</h2>
        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {!isLoading && holders.length === 0 && (
          <p className="text-sm text-muted-foreground">No institutional holder data available.</p>
        )}
        {!isLoading && holders.length > 0 && (
          <>
            {holders.length >= 3 && (
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wide mb-1">
                  Top Holders by % Outstanding
                </p>
                <ReactECharts
                  option={buildTopHoldersOption(sorted)}
                  style={{ height: Math.max(160, Math.min(holders.length, 10) * 28 + 40) }}
                />
              </div>
            )}
            <div className="rounded-md border overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Holder</TableHead>
                    <TableHead className="text-right">Shares</TableHead>
                    <TableHead className="text-right">% Out</TableHead>
                    <TableHead className="text-right">Value</TableHead>
                    <TableHead className="text-right">Date Reported</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sorted.map((h, i) => (
                    <TableRow key={i}>
                      <TableCell className="font-medium">{h.holder}</TableCell>
                      <TableCell className="text-right font-mono text-sm">
                        {fmt(h.shares, "compact")}
                      </TableCell>
                      <TableCell className="text-right font-mono text-sm">
                        {(h.pct_out * 100).toFixed(2)}%
                      </TableCell>
                      <TableCell className="text-right font-mono text-sm">
                        {fmt(h.value, "compact")}
                      </TableCell>
                      <TableCell className="text-right font-mono text-sm">{h.date_reported}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {holdersSnapshot?.fetched_at && (
              <p className="text-xs text-muted-foreground text-right">
                Last updated: {holdersSnapshot.fetched_at.slice(0, 10)}
              </p>
            )}
          </>
        )}
      </section>
    </div>
  );
}
