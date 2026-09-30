import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/layout/AppShell";
import { CompanyTabs } from "@/components/companies/CompanyTabs";
import { OverviewTab } from "@/components/companies/OverviewTab";
import { FinancialsTab } from "@/components/companies/FinancialsTab";
import { MarketDataTab } from "@/components/companies/MarketDataTab";
import { OwnershipTab } from "@/components/companies/OwnershipTab";
import { DividendsTab } from "@/components/companies/DividendsTab";
import { EarningsTab } from "@/components/companies/EarningsTab";
import { OptionsTab } from "@/components/companies/OptionsTab";
import { useCompany, useCompanySnapshots } from "@/hooks/useCompanies";
import { AiSummaryTab } from "@/components/companies/AiSummaryTab";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

export const Route = createFileRoute("/companies/$id")({
  component: CompanyDetailPage,
});

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "financials", label: "Financials" },
  { key: "market", label: "Market Data" },
  { key: "ownership", label: "Ownership" },
  { key: "dividends", label: "Dividends" },
  { key: "earnings", label: "Earnings" },
  { key: "options", label: "Options" },
  { key: "ai-summary", label: "AI Summary" },
];

function CompanyDetailPage() {
  const { id } = Route.useParams();
  const { data: company, isLoading } = useCompany(id);
  const { data: snapshotsData } = useCompanySnapshots(id);
  const [activeTab, setActiveTab] = useState("overview");

  if (isLoading) {
    return (
      <AppShell>
        <p className="text-sm text-muted-foreground">Loading…</p>
      </AppShell>
    );
  }

  if (!company) {
    return (
      <AppShell>
        <p className="text-sm text-muted-foreground">Company not found.</p>
      </AppShell>
    );
  }

  const latestSnapshot = snapshotsData?.results?.[0] ?? null;

  return (
    <AppShell>
      {/* Header */}
      <div className="mb-4 space-y-1">
        <div className="flex items-center gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight font-mono">{company.symbol}</h1>
              {company.exchange && (
                <Badge variant="secondary">{company.exchange_display}</Badge>
              )}
              {company.is_bootstrapped && (
                <Badge variant="secondary" className="text-green-600">
                  Data loaded
                </Badge>
              )}
            </div>
            <p className="text-muted-foreground">{company.name}</p>
          </div>
        </div>
        {(company.sector_name || company.industry_name) && (
          <p className="text-xs text-muted-foreground">
            {company.sector_name}
            {company.industry_name ? ` · ${company.industry_name}` : ""}
          </p>
        )}
      </div>

      <Separator className="mb-4" />

      {/* Tabs */}
      <CompanyTabs tabs={TABS} activeTab={activeTab} onChange={setActiveTab} />

      {activeTab === "overview" && (
        <OverviewTab company={company} snapshot={latestSnapshot} />
      )}
      {activeTab === "financials" && <FinancialsTab companyId={id} />}
      {activeTab === "market" && (
        <MarketDataTab companyId={id} snapshot={latestSnapshot} />
      )}
      {activeTab === "ownership" && (
        <OwnershipTab companyId={id} snapshot={latestSnapshot} />
      )}
      {activeTab === "dividends" && (
        <DividendsTab companyId={id} snapshot={latestSnapshot} />
      )}
      {activeTab === "earnings" && <EarningsTab companyId={id} />}
      {activeTab === "options" && <OptionsTab companyId={id} />}
      {activeTab === "ai-summary" && <AiSummaryTab symbol={company.symbol} />}
    </AppShell>
  );
}
