import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/layout/AppShell";
import { ScheduledTasksTable } from "@/components/tasks/ScheduledTasksTable";
import { TaskResultsTable } from "@/components/tasks/TaskResultsTable";
import { SyncFreshnessWidget } from "@/components/companies/SyncFreshnessChart";
import { SummaryProgressWidget } from "@/components/companies/SummaryProgressWidget";

export const Route = createFileRoute("/tasks")({
  component: TasksPage,
});

const TABS = ["Recent Executions", "Schedules", "Data Sync Freshness", "AI Summary Progress"] as const;
type Tab = (typeof TABS)[number];

function TasksPage() {
  const [activeTab, setActiveTab] = useState<Tab>("Recent Executions");

  return (
    <AppShell>
      <h1 className="text-2xl font-semibold tracking-tight mb-6">Celery Tasks</h1>

      <div className="flex gap-1 border-b mb-6">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium -mb-px border-b-2 transition-colors ${
              activeTab === tab
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === "Recent Executions" && <TaskResultsTable />}
      {activeTab === "Schedules" && <ScheduledTasksTable />}
      {activeTab === "Data Sync Freshness" && <SyncFreshnessWidget />}
      {activeTab === "AI Summary Progress" && <SummaryProgressWidget />}
    </AppShell>
  );
}
