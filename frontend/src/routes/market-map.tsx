import { useEffect, useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/layout/AppShell";
import { SectorIndustrySunburst } from "@/components/companies/SectorIndustrySunburst";
import { SectorIndustryTreemap } from "@/components/companies/SectorIndustryTreemap";
import { useSectors, useIndustries, useMarketHierarchy } from "@/hooks/useCompanies";
import { stripUndefinedNodes, formatMarketCap } from "./market-map.utils";
import { Link } from "@tanstack/react-router";
import type { MarketHierarchyMetric } from "@/types/companies";
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/market-map")({
  component: MarketMapPage,
});

type ChartType = "sunburst" | "treemap";

const PAGE_SIZE = 20;

function MarketMapPage() {
  const [chartType, setChartType] = useState<ChartType>("sunburst");
  const [metric, setMetric] = useState<MarketHierarchyMetric>("count");
  const [activeSector, setActiveSector] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const { data: rawHierarchy } = useMarketHierarchy(metric);
  const hierarchy = useMemo(
    () => (rawHierarchy ? stripUndefinedNodes(rawHierarchy) : undefined),
    [rawHierarchy],
  );
  const { data: sectorsData, isLoading: sectorsLoading } = useSectors();
  const sectors = sectorsData?.results ?? [];

  const activeSectorId = activeSector
    ? sectors.find((s) => s.name === activeSector)?.id
    : undefined;

  const { data: industriesData, isLoading: industriesLoading } = useIndustries({
    sector: activeSectorId,
    search: search || undefined,
    page,
    page_size: PAGE_SIZE,
  });

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset to first page when filters change
    setPage(1);
  }, [activeSectorId, search]);

  const isLoading = sectorsLoading || industriesLoading || !hierarchy;
  const industries = industriesData?.results ?? [];
  const totalCount = industriesData?.count ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

  return (
    <AppShell>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Market Map</h1>
        <div className="flex gap-3">
          <div className="flex gap-1">
            {(["count", "market_cap"] as MarketHierarchyMetric[]).map((m) => (
              <button
                key={m}
                onClick={() => setMetric(m)}
                className={`px-3 py-1 rounded-md text-sm border ${
                  metric === m
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-background border-input"
                }`}
              >
                {m === "count" ? "Count" : "Market Cap"}
              </button>
            ))}
          </div>
          <div className="flex gap-1">
            {(["sunburst", "treemap"] as ChartType[]).map((t) => (
              <button
                key={t}
                onClick={() => setChartType(t)}
                className={`px-3 py-1 rounded-md text-sm capitalize border ${
                  chartType === t
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-background border-input"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}

      {hierarchy && (
        <>
          <div className="mb-4">
            {chartType === "sunburst" ? (
              <SectorIndustrySunburst data={hierarchy} activeSector={activeSector} onSectorClick={setActiveSector} metric={metric} />
            ) : (
              <SectorIndustryTreemap data={hierarchy} onSectorClick={setActiveSector} metric={metric} />
            )}
          </div>

          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <input
                type="search"
                placeholder="Search industries…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="h-9 rounded-md border border-input bg-background px-3 text-sm w-56 focus:outline-none focus:ring-1 focus:ring-ring"
              />
              <select
                value={activeSectorId ?? ""}
                onChange={(e) => {
                  const val = e.target.value;
                  if (!val) {
                    setActiveSector(null);
                  } else {
                    const s = sectors.find((s) => String(s.id) === val);
                    setActiveSector(s?.name ?? null);
                  }
                }}
                className="h-9 rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <option value="">All sectors</option>
                {sectors.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>

              {(activeSector || search) && (
                <button
                  onClick={() => {
                    setActiveSector(null);
                    setSearch("");
                  }}
                  className="text-sm text-muted-foreground hover:text-foreground"
                >
                  Clear filters
                </button>
              )}
            </div>

            {activeSector && (
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">Sector:</span>
                <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-3 py-0.5 text-sm font-medium">
                  {activeSector}
                  <button
                    onClick={() => setActiveSector(null)}
                    className="ml-1 text-xs leading-none"
                    aria-label="Clear sector filter"
                  >
                    ×
                  </button>
                </span>
              </div>
            )}

            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Industry</TableHead>
                    <TableHead>Sector</TableHead>
                    <TableHead className="text-right">
                      {metric === "market_cap" ? "Market Cap" : "Companies"}
                    </TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {industries.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={4} className="text-center text-muted-foreground py-6">
                        No industries found.
                      </TableCell>
                    </TableRow>
                  ) : (
                    industries.map((industry) => (
                      <TableRow key={industry.id}>
                        <TableCell className="font-medium">{industry.name}</TableCell>
                        <TableCell className="text-muted-foreground">
                          {industry.sector_name ? (
                            <button
                              className="hover:underline"
                              onClick={() => setActiveSector(industry.sector_name)}
                            >
                              {industry.sector_name}
                            </button>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {metric === "market_cap"
                            ? industry.total_market_cap != null
                              ? formatMarketCap(industry.total_market_cap)
                              : "—"
                            : industry.company_count}
                        </TableCell>
                        <TableCell>
                          <Link
                            to="/companies"
                            search={{ industry: industry.id }}
                            className="text-sm text-blue-600 hover:underline"
                          >
                            View
                          </Link>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>

            <div className="flex items-center justify-between text-sm text-muted-foreground">
              <span>
                {totalCount} {totalCount === 1 ? "industry" : "industries"}
              </span>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
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
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          </div>
        </>
      )}
    </AppShell>
  );
}
