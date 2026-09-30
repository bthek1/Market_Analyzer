import { apiClient } from "./client";
import type {
  ChartNode,
  Company,
  CompanySnapshot,
  CompanySummary,
  Dividend,
  EarningsDate,
  FinancialStatement,
  Industry,
  InstitutionalHolderSnapshot,
  OptionsChain,
  OptionsExpiry,
  PaginatedResponse,
  PivotedFinancials,
  PriceBar,
  Sector,
  ShortInterest,
  SyncDataType,
  SyncStatus,
} from "@/types/companies";

export interface SyncFreshnessBuckets {
  lt_1h: number;
  h1_6: number;
  h6_24: number;
  d1_7: number;
  d7_30: number;
  gt_30d: number;
  never: number;
}

export interface SyncFreshnessDataType {
  label: string;
  buckets: SyncFreshnessBuckets;
}

export interface GlobalSyncFreshness {
  total_companies: number;
  data_types: SyncFreshnessDataType[];
}

export interface SyncFreshnessMatrixType {
  label: string;
  /** One bucket index per company, aligned with `symbols`. 0 = <1h ... 5 = >30d, 6 = never. */
  buckets: number[];
}

export interface SyncFreshnessMatrix {
  total_companies: number;
  /** Company symbols in alphabetical order. */
  symbols: string[];
  data_types: SyncFreshnessMatrixType[];
}

export interface SummaryFreshness {
  total_companies: number;
  buckets: SyncFreshnessBuckets;
}

export interface CompanyListParams {
  search?: string;
  sector?: number;
  industry?: number;
  exchange?: string;
  is_bootstrapped?: boolean;
  ordering?: string;
  page?: number;
  page_size?: number;
}

export interface IndustryListParams {
  sector?: number;
  search?: string;
  ordering?: string;
  page?: number;
  page_size?: number;
}

export async function listCompanies(
  params?: CompanyListParams,
): Promise<PaginatedResponse<Company>> {
  const { data } = await apiClient.get<PaginatedResponse<Company>>("/api/companies/", { params });
  return data;
}

export async function getCompany(id: number | string): Promise<Company> {
  const { data } = await apiClient.get<Company>(`/api/companies/${id}/`);
  return data;
}

export async function listSectors(): Promise<PaginatedResponse<Sector>> {
  const { data } = await apiClient.get<PaginatedResponse<Sector>>("/api/companies/sectors/");
  return data;
}

export async function listIndustries(params?: IndustryListParams): Promise<PaginatedResponse<Industry>> {
  const { data } = await apiClient.get<PaginatedResponse<Industry>>(
    "/api/companies/industries/",
    { params },
  );
  return data;
}

export async function syncCompanyYF(symbol: string): Promise<Company> {
  const { data } = await apiClient.post<Company>(`/api/companies/yf/sync/${symbol}/`);
  return data;
}

export async function ingestCompany(symbol: string): Promise<Record<string, unknown>> {
  const { data } = await apiClient.post<Record<string, unknown>>(
    `/api/companies/yf/ingest/${symbol}/`,
  );
  return data;
}

export async function listPrices(
  companyId: number,
  params?: { start?: string; end?: string; ordering?: string; page_size?: number; page?: number },
): Promise<PaginatedResponse<PriceBar>> {
  const { data } = await apiClient.get<PaginatedResponse<PriceBar>>(
    `/api/companies/${companyId}/prices/`,
    { params },
  );
  return data;
}

export async function listSnapshots(companyId: number): Promise<PaginatedResponse<CompanySnapshot>> {
  const { data } = await apiClient.get<PaginatedResponse<CompanySnapshot>>(
    `/api/companies/${companyId}/snapshots/`,
  );
  return data;
}

export async function listFinancials(
  companyId: number,
  params?: { statement_type?: string; period?: string },
): Promise<PaginatedResponse<FinancialStatement>> {
  const { data } = await apiClient.get<PaginatedResponse<FinancialStatement>>(
    `/api/companies/${companyId}/financials/`,
    { params },
  );
  return data;
}

export async function listDividends(companyId: number): Promise<PaginatedResponse<Dividend>> {
  const { data } = await apiClient.get<PaginatedResponse<Dividend>>(
    `/api/companies/${companyId}/dividends/`,
  );
  return data;
}

export async function getMarketHierarchy(
  metric: import("@/types/companies").MarketHierarchyMetric = "count",
): Promise<ChartNode[]> {
  const { data } = await apiClient.get<ChartNode[]>("/api/companies/market-hierarchy/", {
    params: { metric },
  });
  return data;
}

export async function listFinancialsPivoted(
  companyId: number,
  params?: { statement_type?: string; period?: string },
): Promise<PivotedFinancials> {
  const { data } = await apiClient.get<PivotedFinancials>(
    `/api/companies/${companyId}/financials/pivoted/`,
    { params },
  );
  return data;
}

export async function getShortInterest(
  companyId: number,
): Promise<PaginatedResponse<ShortInterest>> {
  const { data } = await apiClient.get<PaginatedResponse<ShortInterest>>(
    `/api/companies/${companyId}/short-interest/`,
  );
  return data;
}

export async function getInstitutionalHolders(
  companyId: number,
): Promise<InstitutionalHolderSnapshot> {
  const { data } = await apiClient.get<InstitutionalHolderSnapshot>(
    `/api/companies/${companyId}/institutional-holders/`,
  );
  return data;
}

export async function listEarningsDates(
  companyId: number,
  params?: { is_upcoming?: boolean },
): Promise<PaginatedResponse<EarningsDate>> {
  const { data } = await apiClient.get<PaginatedResponse<EarningsDate>>(
    `/api/companies/${companyId}/earnings-dates/`,
    { params },
  );
  return data;
}

export async function listOptionsExpiries(
  companyId: number,
): Promise<PaginatedResponse<OptionsExpiry>> {
  const { data } = await apiClient.get<PaginatedResponse<OptionsExpiry>>(
    `/api/companies/${companyId}/options/`,
  );
  return data;
}

export async function getOptionsChain(
  companyId: number,
  expiryDate: string,
): Promise<OptionsChain> {
  const { data } = await apiClient.get<OptionsChain>(
    `/api/companies/${companyId}/options/${expiryDate}/`,
  );
  return data;
}

export async function getSyncStatus(companyId: number): Promise<SyncStatus> {
  const { data } = await apiClient.get<SyncStatus>(
    `/api/companies/${companyId}/sync-status/`,
  );
  return data;
}

export async function triggerSync(
  companyId: number,
  dataType: SyncDataType,
): Promise<{ task_id: string; status: string }> {
  const { data } = await apiClient.post<{ task_id: string; status: string }>(
    `/api/companies/${companyId}/sync/${dataType}/`,
  );
  return data;
}

export async function getGlobalSyncFreshness(): Promise<GlobalSyncFreshness> {
  const { data } = await apiClient.get<GlobalSyncFreshness>("/api/companies/sync-freshness/");
  return data;
}

export async function getSyncFreshnessMatrix(): Promise<SyncFreshnessMatrix> {
  const { data } = await apiClient.get<SyncFreshnessMatrix>(
    "/api/companies/sync-freshness/matrix/",
  );
  return data;
}

export async function getSummaryFreshness(): Promise<SummaryFreshness> {
  const { data } = await apiClient.get<SummaryFreshness>("/api/companies/summary-freshness/");
  return data;
}

export async function getLatestSummary(symbol: string): Promise<CompanySummary> {
  const { data } = await apiClient.get<CompanySummary>(
    `/api/companies/${symbol}/summaries/latest/`,
  );
  return data;
}

export async function getSummaryList(symbol: string): Promise<PaginatedResponse<CompanySummary>> {
  const { data } = await apiClient.get<PaginatedResponse<CompanySummary>>(
    `/api/companies/${symbol}/summaries/`,
  );
  return data;
}

export async function triggerSummaryGeneration(
  symbol: string,
): Promise<{ task_id: string; status: string }> {
  const { data } = await apiClient.post(`/api/companies/${symbol}/summaries/generate/`);
  return data;
}
