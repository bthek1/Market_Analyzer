import { useCallback, useEffect, useRef, useState } from "react";
import { createFileRoute, useSearch } from "@tanstack/react-router";
import { z } from "zod";
import { AppShell } from "@/components/layout/AppShell";
import { CompanyTable } from "@/components/companies/CompanyTable";
import { useCompanySearch, useSectors, useIndustries } from "@/hooks/useCompanies";
import type { CompanyListParams } from "@/api/companies";
import { Input } from "@/components/ui/input";

const companiesSearchSchema = z.object({
  sector: z.number().optional(),
  industry: z.number().optional(),
});

export const Route = createFileRoute("/companies/")({
  validateSearch: companiesSearchSchema,
  component: CompaniesPage,
});

const EXCHANGES = ["NYSE", "NASDAQ", "AMEX", "NYSE_ARCA", "LSE", "ASX", "TSX", "OTHER"];
const PAGE_SIZE = 25;

function CompaniesPage() {
  const { sector: sectorParam, industry: industryParam } = useSearch({ from: "/companies/" });

  const [params, setParams] = useState<CompanyListParams>({
    page: 1,
    page_size: PAGE_SIZE,
    ordering: "symbol",
    sector: sectorParam,
    industry: industryParam,
  });

  const [searchInput, setSearchInput] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { data, isLoading } = useCompanySearch(params);
  const { data: sectorsData } = useSectors();
  const sectors = sectorsData?.results ?? [];
  const { data: industriesData } = useIndustries(
    params.sector ? { sector: params.sector } : undefined,
  );
  const industries = industriesData?.results ?? [];

  const mergeParams = useCallback((patch: Partial<CompanyListParams>) => {
    setParams((prev) => ({ ...prev, ...patch }));
  }, []);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      mergeParams({ search: searchInput || undefined, page: 1 });
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [searchInput, mergeParams]);

  return (
    <AppShell>
      <h1 className="text-2xl font-semibold tracking-tight mb-6">Companies</h1>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-6">
        <Input
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="Search symbol or name…"
          className="w-64"
        />

        <select
          className="h-9 rounded-md border border-input bg-background px-3 text-sm"
          value={params.sector ?? ""}
          onChange={(e) =>
            mergeParams({ sector: e.target.value ? Number(e.target.value) : undefined, page: 1 })
          }
        >
          <option value="">All sectors</option>
          {sectors.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>

        <select
          className="h-9 rounded-md border border-input bg-background px-3 text-sm"
          value={params.industry ?? ""}
          onChange={(e) =>
            mergeParams({ industry: e.target.value ? Number(e.target.value) : undefined, page: 1 })
          }
        >
          <option value="">All industries</option>
          {industries.map((i) => (
            <option key={i.id} value={i.id}>
              {i.name}
            </option>
          ))}
        </select>

        <select
          className="h-9 rounded-md border border-input bg-background px-3 text-sm"
          value={params.exchange ?? ""}
          onChange={(e) =>
            mergeParams({ exchange: e.target.value || undefined, page: 1 })
          }
        >
          <option value="">All exchanges</option>
          {EXCHANGES.map((ex) => (
            <option key={ex} value={ex}>
              {ex}
            </option>
          ))}
        </select>

        <label className="flex items-center gap-2 h-9 cursor-pointer text-sm">
          <input
            type="checkbox"
            className="rounded"
            checked={params.is_bootstrapped === true}
            onChange={(e) =>
              mergeParams({ is_bootstrapped: e.target.checked ? true : undefined, page: 1 })
            }
          />
          Data loaded only
        </label>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}

      {data && (
        <CompanyTable
          companies={data.results}
          count={data.count}
          params={params}
          onParamsChange={mergeParams}
        />
      )}
    </AppShell>
  );
}
