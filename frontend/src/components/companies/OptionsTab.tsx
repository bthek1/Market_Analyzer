import { useState } from "react";
import { useOptionsChain, useOptionsExpiries } from "@/hooks/useCompanies";
import { SyncPanel } from "@/components/companies/SyncPanel";
import type { OptionsContract } from "@/types/companies";
import { cn } from "@/lib/utils";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

function fmt(v: string | number | null, decimals = 2): string {
  if (v === null || v === undefined) return "—";
  const n = typeof v === "string" ? parseFloat(v) : v;
  if (isNaN(n)) return "—";
  return n.toFixed(decimals);
}

function fmtIV(v: number | null): string {
  if (v === null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function ContractsTable({ contracts }: { contracts: OptionsContract[] }) {
  if (contracts.length === 0) return <p className="text-sm text-muted-foreground py-2">No contracts.</p>;
  return (
    <div className="rounded-md border overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Strike</TableHead>
            <TableHead className="text-right">Last</TableHead>
            <TableHead className="text-right">Bid</TableHead>
            <TableHead className="text-right">Ask</TableHead>
            <TableHead className="text-right">Volume</TableHead>
            <TableHead className="text-right">Open Interest</TableHead>
            <TableHead className="text-right">IV</TableHead>
            <TableHead className="text-right">ITM</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {contracts.map((c) => (
            <TableRow
              key={c.id}
              className={cn(c.in_the_money ? "bg-primary/5" : "")}
            >
              <TableCell className="font-mono text-sm font-medium">{fmt(c.strike)}</TableCell>
              <TableCell className="text-right font-mono text-sm">{fmt(c.last_price)}</TableCell>
              <TableCell className="text-right font-mono text-sm">{fmt(c.bid)}</TableCell>
              <TableCell className="text-right font-mono text-sm">{fmt(c.ask)}</TableCell>
              <TableCell className="text-right font-mono text-sm">
                {c.volume !== null ? c.volume.toLocaleString() : "—"}
              </TableCell>
              <TableCell className="text-right font-mono text-sm">
                {c.open_interest !== null ? c.open_interest.toLocaleString() : "—"}
              </TableCell>
              <TableCell className="text-right font-mono text-sm">{fmtIV(c.implied_volatility)}</TableCell>
              <TableCell className="text-right font-mono text-sm">
                {c.in_the_money === null ? "—" : c.in_the_money ? "Yes" : "No"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

interface OptionsTabProps {
  companyId: number | string;
}

export function OptionsTab({ companyId }: OptionsTabProps) {
  const { data: expiriesData, isLoading: expiriesLoading } = useOptionsExpiries(companyId);
  const expiries = expiriesData?.results ?? [];

  const [selectedExpiry, setSelectedExpiry] = useState<string | null>(null);
  const [chainTab, setChainTab] = useState<"calls" | "puts">("calls");

  const activeExpiry = selectedExpiry ?? expiries[0]?.expiry_date ?? null;

  const { data: chain, isLoading: chainLoading } = useOptionsChain(companyId, activeExpiry);

  const id = Number(companyId);

  if (expiriesLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;

  if (expiries.length === 0) {
    return (
      <div className="space-y-4">
        <div className="border-b pb-3">
          <SyncPanel companyId={id} dataType="options" label="Options" />
        </div>
        <p className="text-sm text-muted-foreground">
          No options data available. Run a full ingest to load options chains.
        </p>
      </div>
    );
  }

  const contracts = chainTab === "calls" ? (chain?.calls ?? []) : (chain?.puts ?? []);

  return (
    <div className="space-y-6">
      {/* Sync */}
      <div className="border-b pb-3">
        <SyncPanel companyId={id} dataType="options" />
      </div>

      {/* Expiry picker */}
      <div className="space-y-2">
        <p className="text-xs text-muted-foreground uppercase tracking-wide">Expiry Date</p>
        <div className="flex flex-wrap gap-2">
          {expiries.map((e) => (
            <button
              key={e.expiry_date}
              onClick={() => setSelectedExpiry(e.expiry_date)}
              className={cn(
                "px-3 py-1.5 text-sm rounded-md border transition-colors",
                activeExpiry === e.expiry_date
                  ? "bg-primary text-primary-foreground border-primary"
                  : "border-input text-muted-foreground hover:text-foreground",
              )}
            >
              {e.expiry_date}
            </button>
          ))}
        </div>
      </div>

      {/* Calls / Puts toggle */}
      <div className="flex gap-1 border-b">
        {(["calls", "puts"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setChainTab(t)}
            className={cn(
              "px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors capitalize",
              chainTab === t
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {chainLoading && <p className="text-sm text-muted-foreground">Loading chain…</p>}
      {!chainLoading && <ContractsTable contracts={contracts} />}
    </div>
  );
}
