import { useState } from "react";
import ReactECharts from "echarts-for-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { useCompanyFinancialsPivoted } from "@/hooks/useCompanies";
import { SyncPanel } from "@/components/companies/SyncPanel";
import {
  buildRevenueOption,
  buildBalanceSheetOption,
  buildDebtEquityOption,
  buildMarginsOption,
  buildCashFlowOption,
} from "./FinancialsTab.chartOptions";

type StatementType = "income" | "balance" | "cashflow";
type Period = "annual" | "quarterly";

function fmt(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(v);
}

// ---------------------------------------------------------------------------
// Main FinancialsTab
// ---------------------------------------------------------------------------

interface FinancialsTabProps {
  companyId: number | string;
}

export function FinancialsTab({ companyId }: FinancialsTabProps) {
  const [stmtType, setStmtType] = useState<StatementType>("income");
  const [period, setPeriod] = useState<Period>("annual");
  const { data, isLoading } = useCompanyFinancialsPivoted(companyId, {
    statement_type: stmtType,
    period,
  });

  const dates = data?.dates ?? [];
  const rows = data?.rows ?? [];

  const stmtLabels: Record<StatementType, string> = {
    income: "Income Statement",
    balance: "Balance Sheet",
    cashflow: "Cash Flow",
  };

  const revenueNonNull =
    stmtType === "income" &&
    rows.some((r) => r.metric === "Total Revenue" && r.values.some((v) => v !== null));

  const marginsOption = stmtType === "income" ? buildMarginsOption(dates, rows) : null;
  const cashFlowOption = stmtType === "cashflow" ? buildCashFlowOption(dates, rows) : null;
  const balanceSheetOption = stmtType === "balance" ? buildBalanceSheetOption(dates, rows) : null;
  const debtEquityOption = stmtType === "balance" ? buildDebtEquityOption(dates, rows) : null;

  const id = Number(companyId);

  return (
    <div className="space-y-4">
      {/* Sync */}
      <div className="border-b pb-3">
        <SyncPanel companyId={id} dataType="financials" label="Financials" />
      </div>

      {/* Controls */}
      <div className="flex gap-2 flex-wrap">
        {(Object.keys(stmtLabels) as StatementType[]).map((t) => (
          <Button
            key={t}
            variant={stmtType === t ? "default" : "outline"}
            size="sm"
            onClick={() => setStmtType(t)}
          >
            {stmtLabels[t]}
          </Button>
        ))}
        <span className="ml-auto flex gap-2">
          {(["annual", "quarterly"] as Period[]).map((p) => (
            <Button
              key={p}
              variant={period === p ? "default" : "outline"}
              size="sm"
              onClick={() => setPeriod(p)}
            >
              {p.charAt(0).toUpperCase() + p.slice(1)}
            </Button>
          ))}
        </span>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {!isLoading && rows.length === 0 && (
        <p className="text-sm text-muted-foreground py-2">No financial data available.</p>
      )}

      {!isLoading && rows.length > 0 && (
        <>
          {/* Revenue chart */}
          {revenueNonNull && (
            <div>
              <p className="text-xs text-muted-foreground mb-1 uppercase tracking-wide">Revenue & Net Income</p>
              <ReactECharts option={buildRevenueOption(dates, rows)} style={{ height: 220 }} />
            </div>
          )}

          {/* Margins chart */}
          {marginsOption && (
            <div>
              <p className="text-xs text-muted-foreground mb-1 uppercase tracking-wide">Profit Margins</p>
              <ReactECharts option={marginsOption} style={{ height: 200 }} />
            </div>
          )}

          {/* Cash flow chart */}
          {cashFlowOption && (
            <div>
              <p className="text-xs text-muted-foreground mb-1 uppercase tracking-wide">Cash Flow</p>
              <ReactECharts option={cashFlowOption} style={{ height: 200 }} />
            </div>
          )}

          {/* Balance sheet stacked bar */}
          {balanceSheetOption && (
            <div>
              <p className="text-xs text-muted-foreground mb-1 uppercase tracking-wide">
                Balance Sheet Composition
              </p>
              <ReactECharts option={balanceSheetOption} style={{ height: 220 }} />
            </div>
          )}

          {/* Debt vs equity trend */}
          {debtEquityOption && (
            <div>
              <p className="text-xs text-muted-foreground mb-1 uppercase tracking-wide">
                Debt vs Equity Trend
              </p>
              <ReactECharts option={debtEquityOption} style={{ height: 200 }} />
            </div>
          )}

          {/* Data table */}
          <div className="rounded-md border overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-[160px]">Metric</TableHead>
                  {dates.map((d) => (
                    <TableHead key={d} className="text-right">
                      {d}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map(({ metric, values }) => (
                  <TableRow key={metric}>
                    <TableCell className="font-medium">{metric}</TableCell>
                    {values.map((v, i) => (
                      <TableCell key={dates[i]} className="text-right font-mono text-sm">
                        {fmt(v)}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </>
      )}
    </div>
  );
}
