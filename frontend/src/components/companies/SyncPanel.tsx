import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/api/queryKeys";
import { Button } from "@/components/ui/button";
import { useSyncStatus, useTaskStatus, useTriggerSync } from "@/hooks/useCompanies";
import type { SyncDataType } from "@/types/companies";

interface SyncPanelProps {
  companyId: number;
  dataType: SyncDataType;
  label?: string;
}

const DATA_TYPE_QUERY_KEYS: Record<SyncDataType, (id: number) => readonly unknown[]> = {
  profile: (id) => queryKeys.companies.detail(id),
  prices: (id) => queryKeys.companies.prices(id),
  snapshot: (id) => queryKeys.companies.snapshots(id),
  financials: (id) => queryKeys.companies.financialsPivoted(id),
  dividends: (id) => queryKeys.companies.dividends(id),
  short_interest: (id) => queryKeys.companies.shortInterest(id),
  institutional: (id) => queryKeys.companies.institutionalHolders(id),
  earnings: (id) => queryKeys.companies.earningsDates(id),
  options: (id) => queryKeys.companies.optionsExpiries(id),
};

function timeAgo(dateStr: string): string {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (seconds < 0) {
    // Future timestamp — show as absolute date (e.g. a fetched_at set in the future by clock skew)
    return new Date(dateStr).toLocaleDateString();
  }
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function SyncPanel({ companyId, dataType, label }: SyncPanelProps) {
  const [taskId, setTaskId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data: syncStatus } = useSyncStatus(companyId);
  const triggerMutation = useTriggerSync(companyId);
  const taskQuery = useTaskStatus(taskId);

  const taskStatus = taskQuery.data?.status;
  const isTerminal = taskStatus === "SUCCESS" || taskStatus === "FAILURE";

  useEffect(() => {
    if (!taskId || !isTerminal) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- clear task id once the polled task reaches a terminal state
    setTaskId(null);
    queryClient.invalidateQueries({ queryKey: queryKeys.companies.syncStatus(companyId) });
    queryClient.invalidateQueries({ queryKey: DATA_TYPE_QUERY_KEYS[dataType](companyId) });
  }, [taskId, isTerminal, companyId, dataType, queryClient]);

  const isPending = !!taskId && !isTerminal;
  const lastSynced = syncStatus?.[dataType];

  function handleSync() {
    triggerMutation.mutate(dataType, {
      onSuccess: (data) => {
        setTaskId(data.task_id);
        // Fallback: if task result never lands in DB (404 forever), still refresh after 15s
        setTimeout(() => {
          setTaskId(null);
          queryClient.invalidateQueries({ queryKey: queryKeys.companies.syncStatus(companyId) });
          queryClient.invalidateQueries({ queryKey: DATA_TYPE_QUERY_KEYS[dataType](companyId) });
        }, 15_000);
      },
    });
  }

  return (
    <div className="flex items-center gap-3 text-sm text-muted-foreground">
      {label && <span className="font-medium text-foreground">{label}</span>}
      <span>
        {lastSynced ? `Last synced: ${timeAgo(lastSynced)}` : "Never synced"}
      </span>
      <Button
        size="sm"
        variant="outline"
        disabled={isPending || triggerMutation.isPending}
        onClick={handleSync}
      >
        {isPending ? (
          <span className="flex items-center gap-1">
            <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
            Syncing…
          </span>
        ) : (
          "Sync"
        )}
      </Button>
      {taskStatus === "FAILURE" && (
        <span className="text-destructive text-sm">Sync failed.</span>
      )}
    </div>
  );
}
