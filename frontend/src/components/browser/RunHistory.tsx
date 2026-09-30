import { useQuery } from "@tanstack/react-query";
import { fetchBrowserRunDetail, fetchBrowserRuns } from "@/api/browser";
import { queryKeys } from "@/api/queryKeys";
import { cn } from "@/lib/utils";
import type { BrowserRunDetail, BrowserRunSummary } from "@/types/browser";

const STATUS_DOT: Record<string, string> = {
  running: "bg-blue-500 animate-pulse",
  done: "bg-emerald-500",
  error: "bg-destructive",
  stopped: "bg-muted-foreground",
};

function groupByDay(runs: BrowserRunSummary[]) {
  const today = new Date().toDateString();
  const groups = new Map<string, BrowserRunSummary[]>();
  for (const run of runs) {
    const date = new Date(run.created_at).toDateString();
    const label = date === today ? "Today" : date;
    groups.set(label, [...(groups.get(label) ?? []), run]);
  }
  return [...groups.entries()];
}

interface RunHistoryProps {
  activeId: string | null;
  onSelect: (detail: BrowserRunDetail) => void;
}

/**
 * This page's own history. It reads /api/llm/browser/history/ directly - browser runs do
 * not appear in the Agents page's combined run feed.
 */
export function RunHistory({ activeId, onSelect }: RunHistoryProps) {
  const { data: runs = [], isLoading } = useQuery({
    queryKey: queryKeys.browser.runs(),
    queryFn: fetchBrowserRuns,
  });

  const open = async (id: string) => {
    const detail = await fetchBrowserRunDetail(id);
    onSelect(detail);
  };

  return (
    <aside className="flex w-56 shrink-0 flex-col gap-3 border-r pr-3">
      <h2 className="text-xs font-semibold text-muted-foreground">History</h2>

      {isLoading && <p className="text-xs text-muted-foreground">Loading...</p>}
      {!isLoading && runs.length === 0 && (
        <p className="text-xs text-muted-foreground">No searches yet.</p>
      )}

      {groupByDay(runs).map(([label, group]) => (
        <div key={label} className="flex flex-col gap-1">
          <p className="text-[11px] tracking-wide text-muted-foreground uppercase">
            {label}
          </p>
          {group.map((run) => (
            <button
              key={run.id}
              type="button"
              onClick={() => open(run.id)}
              className={cn(
                "flex items-start gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-muted",
                run.id === activeId && "bg-muted",
              )}
            >
              <span
                className={cn(
                  "mt-1 size-1.5 shrink-0 rounded-full",
                  STATUS_DOT[run.status] ?? "bg-muted-foreground",
                )}
                aria-label={run.status}
              />
              <span className="line-clamp-2">{run.query}</span>
            </button>
          ))}
        </div>
      ))}
    </aside>
  );
}
