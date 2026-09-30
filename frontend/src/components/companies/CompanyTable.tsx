import React from "react";
import { Link } from "@tanstack/react-router";
import type { Company } from "@/types/companies";
import type { CompanyListParams } from "@/api/companies";
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface CompanyTableProps {
  companies: Company[];
  count: number;
  params: CompanyListParams;
  onParamsChange: (p: Partial<CompanyListParams>) => void;
}

function SortHeader({
  label,
  field,
  current,
  onChange,
}: {
  label: string;
  field: string;
  current: string | undefined;
  onChange: (ordering: string) => void;
}) {
  const isAsc = current === field;
  const isDesc = current === `-${field}`;
  const next = isAsc ? `-${field}` : field;
  return (
    <button
      onClick={() => onChange(next)}
      className="flex items-center gap-1 font-medium hover:text-foreground"
    >
      {label}
      <span className="text-xs text-muted-foreground">
        {isAsc ? "▲" : isDesc ? "▼" : "⇅"}
      </span>
    </button>
  );
}

function fmtMarketCap(value: number | null): string {
  if (value == null) return "—";
  if (value >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
  if (value >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (value >= 1e6) return `$${(value / 1e6).toFixed(2)}M`;
  return `$${value.toLocaleString()}`;
}

function fmtPe(value: number | null): string {
  if (value == null || value <= 0) return "—";
  return value.toFixed(1) + "x";
}

function fmtPct(value: number | null): string {
  if (value == null) return "—";
  return (value * 100).toFixed(2) + "%";
}

export function CompanyTable({ companies, count, params, onParamsChange }: CompanyTableProps) {
  const page = params.page ?? 1;
  const pageSize = params.page_size ?? 20;
  const totalPages = Math.max(1, Math.ceil(count / pageSize));

  if (companies.length === 0 && count === 0) {
    return (
      <p className="text-sm text-muted-foreground py-4 text-center">No companies found.</p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>
                <SortHeader
                  label="Symbol"
                  field="symbol"
                  current={params.ordering}
                  onChange={(ordering) => onParamsChange({ ordering, page: 1 })}
                />
              </TableHead>
              <TableHead>
                <SortHeader
                  label="Name"
                  field="name"
                  current={params.ordering}
                  onChange={(ordering) => onParamsChange({ ordering, page: 1 })}
                />
              </TableHead>
              <TableHead>Exchange</TableHead>
              <TableHead>Sector</TableHead>
              <TableHead>Industry</TableHead>
              <TableHead className="text-right">
                <SortHeader
                  label="Mkt Cap"
                  field="market_cap"
                  current={params.ordering}
                  onChange={(ordering) => onParamsChange({ ordering, page: 1 })}
                />
              </TableHead>
              <TableHead className="text-right">
                <SortHeader
                  label="P/E"
                  field="trailing_pe"
                  current={params.ordering}
                  onChange={(ordering) => onParamsChange({ ordering, page: 1 })}
                />
              </TableHead>
              <TableHead className="text-right">
                <SortHeader
                  label="Net Margin"
                  field="profit_margins"
                  current={params.ordering}
                  onChange={(ordering) => onParamsChange({ ordering, page: 1 })}
                />
              </TableHead>
              <TableHead className="text-right">
                <SortHeader
                  label="Div Yield"
                  field="dividend_yield"
                  current={params.ordering}
                  onChange={(ordering) => onParamsChange({ ordering, page: 1 })}
                />
              </TableHead>
              <TableHead>Data</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {companies.map((company) => {
              const to = "/companies/$id" as const;
              const linkParams = { id: String(company.id) };
              const cellLink = (content: React.ReactNode) => (
                <Link
                  to={to}
                  params={linkParams}
                  className="block w-full h-full"
                >
                  {content}
                </Link>
              );
              return (
                <TableRow key={company.id} className="cursor-pointer p-0">
                  <TableCell className="font-mono font-medium p-0">
                    {cellLink(
                      <span className="block px-2 py-2 underline-offset-4 hover:underline">
                        {company.symbol}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="p-0">
                    {cellLink(<span className="block px-2 py-2">{company.name}</span>)}
                  </TableCell>
                  <TableCell className="p-0">
                    {cellLink(
                      <span className="block px-2 py-2">
                        {company.exchange ? (
                          <Badge variant="secondary">{company.exchange_display}</Badge>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground p-0">
                    {cellLink(
                      <span className="block px-2 py-2">{company.sector_name || "—"}</span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground p-0">
                    {cellLink(
                      <span className="block px-2 py-2">{company.industry_name || "—"}</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums p-0">
                    {cellLink(
                      <span className="block px-2 py-2 text-right">
                        {fmtMarketCap(company.market_cap)}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground p-0">
                    {cellLink(
                      <span className="block px-2 py-2 text-right">
                        {fmtPe(company.trailing_pe)}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground p-0">
                    {cellLink(
                      <span className="block px-2 py-2 text-right">
                        {fmtPct(company.profit_margins)}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground p-0">
                    {cellLink(
                      <span className="block px-2 py-2 text-right">
                        {fmtPct(company.dividend_yield)}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="p-0">
                    {cellLink(
                      <span className="block px-2 py-2">
                        <span
                          className={`inline-block w-2 h-2 rounded-full ${
                            company.is_bootstrapped ? "bg-green-500" : "bg-muted-foreground/30"
                          }`}
                          title={company.is_bootstrapped ? "Data loaded" : "No data"}
                        />
                      </span>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>
          {count} {count === 1 ? "company" : "companies"}
        </span>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => onParamsChange({ page: page - 1 })}
          >
            Previous
          </Button>
          <span>
            Page {page} of {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages}
            onClick={() => onParamsChange({ page: page + 1 })}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
