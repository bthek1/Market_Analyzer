import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type CompanyListParams,
  type IndustryListParams,
  getCompany,
  getGlobalSyncFreshness,
  getSyncFreshnessMatrix,
  getSummaryFreshness,
  getInstitutionalHolders,
  getMarketHierarchy,
  getOptionsChain,
  getShortInterest,
  getSyncStatus,
  listCompanies,
  listDividends,
  listEarningsDates,
  listFinancials,
  listFinancialsPivoted,
  listIndustries,
  listOptionsExpiries,
  listPrices,
  listSectors,
  listSnapshots,
  syncCompanyYF,
  triggerSync,
} from "@/api/companies";
import { getTaskResult } from "@/api/tasks";
import type { SyncDataType } from "@/types/companies";
import { queryKeys } from "@/api/queryKeys";

export function useCompanySearch(params?: CompanyListParams) {
  return useQuery({
    queryKey: queryKeys.companies.list(params),
    queryFn: () => listCompanies(params),
  });
}

export function useCompany(id: number | string) {
  return useQuery({
    queryKey: queryKeys.companies.detail(id),
    queryFn: () => getCompany(id),
    enabled: !!id,
  });
}

export function useSectors() {
  return useQuery({
    queryKey: queryKeys.companies.sectors(),
    queryFn: listSectors,
  });
}

export function useIndustries(params?: IndustryListParams) {
  return useQuery({
    queryKey: queryKeys.companies.industries(params),
    queryFn: () => listIndustries(params),
  });
}

export function useSyncCompanyYF() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (symbol: string) => syncCompanyYF(symbol),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.companies.all() });
    },
  });
}

export function useCompanySnapshots(companyId: number | string) {
  const id = Number(companyId);
  return useQuery({
    queryKey: queryKeys.companies.snapshots(id),
    queryFn: () => listSnapshots(id),
    enabled: !!id,
  });
}

export function useCompanyFinancials(
  companyId: number | string,
  params?: { statement_type?: string; period?: string },
) {
  const id = Number(companyId);
  return useQuery({
    queryKey: [...queryKeys.companies.financials(id), params],
    queryFn: () => listFinancials(id, params),
    enabled: !!id,
  });
}

export function useCompanyPrices(
  companyId: number | string,
  params?: { start?: string; end?: string; ordering?: string; page_size?: number; page?: number },
) {
  const id = Number(companyId);
  return useQuery({
    queryKey: [...queryKeys.companies.prices(id), params],
    queryFn: () => listPrices(id, params),
    enabled: !!id,
  });
}

export function useCompanyDividends(companyId: number | string) {
  const id = Number(companyId);
  return useQuery({
    queryKey: queryKeys.companies.dividends(id),
    queryFn: () => listDividends(id),
    enabled: !!id,
  });
}

export function useMarketHierarchy(
  metric: import("@/types/companies").MarketHierarchyMetric = "count",
) {
  return useQuery({
    queryKey: queryKeys.companies.marketHierarchy(metric),
    queryFn: () => getMarketHierarchy(metric),
  });
}

export function useCompanyFinancialsPivoted(
  companyId: number | string,
  params?: { statement_type?: string; period?: string },
) {
  const id = Number(companyId);
  return useQuery({
    queryKey: [...queryKeys.companies.financialsPivoted(id), params],
    queryFn: () => listFinancialsPivoted(id, params),
    enabled: !!id,
  });
}

export function useShortInterest(companyId: number | string) {
  const id = Number(companyId);
  return useQuery({
    queryKey: queryKeys.companies.shortInterest(id),
    queryFn: () => getShortInterest(id),
    enabled: !!id,
  });
}

export function useInstitutionalHolders(companyId: number | string) {
  const id = Number(companyId);
  return useQuery({
    queryKey: queryKeys.companies.institutionalHolders(id),
    queryFn: () => getInstitutionalHolders(id),
    enabled: !!id,
  });
}

export function useEarningsDates(
  companyId: number | string,
  params?: { is_upcoming?: boolean },
) {
  const id = Number(companyId);
  return useQuery({
    queryKey: queryKeys.companies.earningsDates(id, params),
    queryFn: () => listEarningsDates(id, params),
    enabled: !!id,
  });
}

export function useOptionsExpiries(companyId: number | string) {
  const id = Number(companyId);
  return useQuery({
    queryKey: queryKeys.companies.optionsExpiries(id),
    queryFn: () => listOptionsExpiries(id),
    enabled: !!id,
  });
}

export function useOptionsChain(companyId: number | string, expiryDate: string | null) {
  const id = Number(companyId);
  return useQuery({
    queryKey: queryKeys.companies.optionsChain(id, expiryDate ?? ""),
    queryFn: () => getOptionsChain(id, expiryDate!),
    enabled: !!id && !!expiryDate,
  });
}

export function useSyncStatus(companyId: number) {
  return useQuery({
    queryKey: queryKeys.companies.syncStatus(companyId),
    queryFn: () => getSyncStatus(companyId),
    staleTime: 30_000,
    enabled: !!companyId,
  });
}

export function useTaskStatus(taskId: string | null) {
  return useQuery({
    queryKey: queryKeys.tasks.result(taskId ?? ""),
    queryFn: async () => {
      try {
        return await getTaskResult(taskId!);
      } catch {
        // Task not yet stored in DB (still queued/running) — treat as PENDING
        return { task_id: taskId!, status: "PENDING" as const, result: null };
      }
    },
    enabled: !!taskId,
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === "SUCCESS" || s === "FAILURE" ? false : 2000;
    },
  });
}

export function useTriggerSync(companyId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (dataType: SyncDataType) => triggerSync(companyId, dataType),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.companies.syncStatus(companyId),
      });
    },
  });
}

export function useSyncFreshness() {
  return useQuery({
    queryKey: queryKeys.companies.syncFreshness(),
    queryFn: getGlobalSyncFreshness,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

export function useSyncFreshnessMatrix(enabled = true) {
  return useQuery({
    queryKey: queryKeys.companies.syncFreshnessMatrix(),
    queryFn: getSyncFreshnessMatrix,
    enabled,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

export function useSummaryFreshness() {
  return useQuery({
    queryKey: queryKeys.companies.summaryFreshness(),
    queryFn: getSummaryFreshness,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}
