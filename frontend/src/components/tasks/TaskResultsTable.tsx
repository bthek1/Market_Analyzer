import { Fragment, useState } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useTaskResults } from "@/hooks/useTasks";
import { TaskStatusBadge } from "./TaskStatusBadge";
import type { TaskStatus } from "@/types/tasks";
import { formatDateTime } from "@/lib/utils";

const STATUS_OPTIONS: { label: string; value: string }[] = [
  { label: "All", value: "" },
  { label: "Success", value: "SUCCESS" },
  { label: "Failure", value: "FAILURE" },
  { label: "Pending", value: "PENDING" },
  { label: "Started", value: "STARTED" },
];

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return formatDateTime(new Date(iso));
}

function shortTaskName(name: string | null): string {
  if (!name) return "—";
  const parts = name.split(".");
  return parts[parts.length - 1];
}

function tryParseJson(raw: string | null): string {
  if (!raw) return "—";
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

export function TaskResultsTable() {
  const [statusFilter, setStatusFilter] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const { data, isLoading, dataUpdatedAt } = useTaskResults(statusFilter || undefined);

  const results = data?.results ?? [];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex gap-1">
          {STATUS_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setStatusFilter(opt.value)}
              className={`px-3 py-1 rounded-md text-sm transition-colors ${
                statusFilter === opt.value
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        {dataUpdatedAt > 0 && (
          <span className="text-xs text-muted-foreground">
            Updated {new Date(dataUpdatedAt).toLocaleTimeString()}
          </span>
        )}
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">Loading...</p>}

      {!isLoading && results.length === 0 && (
        <p className="text-sm text-muted-foreground py-4 text-center">No task results found.</p>
      )}

      {results.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Task</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Worker</TableHead>
              <TableHead>Started</TableHead>
              <TableHead>Finished</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {results.map((r) => (
              <Fragment key={r.task_id}>
                <TableRow
                  key={r.task_id}
                  className="cursor-pointer hover:bg-muted/50"
                  onClick={() => setExpandedId(expandedId === r.task_id ? null : r.task_id)}
                >
                  <TableCell className="font-mono text-xs">
                    {shortTaskName(r.task_name)}
                  </TableCell>
                  <TableCell>
                    <TaskStatusBadge status={r.status as TaskStatus} />
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {r.worker ?? "—"}
                  </TableCell>
                  <TableCell className="text-xs">{formatDate(r.date_started)}</TableCell>
                  <TableCell className="text-xs">{formatDate(r.date_done)}</TableCell>
                </TableRow>

                {expandedId === r.task_id && (
                  <TableRow>
                    <TableCell colSpan={5} className="bg-muted/30 p-4">
                      <div className="space-y-2 text-xs">
                        <div>
                          <span className="font-medium text-muted-foreground">Task ID: </span>
                          <span className="font-mono">{r.task_id}</span>
                        </div>
                        {r.task_name && (
                          <div>
                            <span className="font-medium text-muted-foreground">Full name: </span>
                            <span className="font-mono">{r.task_name}</span>
                          </div>
                        )}
                        <div>
                          <span className="font-medium text-muted-foreground block mb-1">Result:</span>
                          <pre className="bg-background rounded p-2 overflow-x-auto text-xs">
                            {tryParseJson(r.result)}
                          </pre>
                        </div>
                        {r.traceback && (
                          <div>
                            <span className="font-medium text-destructive block mb-1">Traceback:</span>
                            <pre className="bg-destructive/5 text-destructive rounded p-2 overflow-x-auto text-xs whitespace-pre-wrap">
                              {r.traceback}
                            </pre>
                          </div>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            ))}
          </TableBody>
        </Table>
      )}

      {data && data.count > results.length && (
        <p className="text-xs text-muted-foreground text-center">
          Showing {results.length} of {data.count} results
        </p>
      )}
    </div>
  );
}
