import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useSchedules, useToggleSchedule, useTriggerTask } from "@/hooks/useTasks";
import { formatDateTime } from "@/lib/utils";

function formatDate(iso: string | null): string {
  if (!iso) return "Never";
  return formatDateTime(new Date(iso));
}

function shortTaskName(task: string): string {
  const parts = task.split(".");
  return parts[parts.length - 1];
}

export function ScheduledTasksTable() {
  const { data: schedules, isLoading } = useSchedules();
  const toggle = useToggleSchedule();
  const trigger = useTriggerTask();
  const [triggeredId, setTriggeredId] = useState<number | null>(null);

  async function handleTrigger(id: number) {
    setTriggeredId(id);
    try {
      await trigger.mutateAsync(id);
    } finally {
      setTriggeredId(null);
    }
  }

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading...</p>;
  if (!schedules?.length) return <p className="text-sm text-muted-foreground py-4 text-center">No scheduled tasks.</p>;

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Task</TableHead>
          <TableHead>Schedule</TableHead>
          <TableHead>Last Run</TableHead>
          <TableHead>Next Run</TableHead>
          <TableHead className="text-right">Runs</TableHead>
          <TableHead className="text-center">Enabled</TableHead>
          <TableHead />
        </TableRow>
      </TableHeader>
      <TableBody>
        {schedules.map((task) => (
          <TableRow key={task.id}>
            <TableCell className="font-medium text-sm">{task.name}</TableCell>
            <TableCell className="font-mono text-xs text-muted-foreground">
              {shortTaskName(task.task)}
            </TableCell>
            <TableCell className="text-xs">{task.interval_display}</TableCell>
            <TableCell className="text-xs">{formatDate(task.last_run_at)}</TableCell>
            <TableCell className="text-xs">{task.enabled ? formatDate(task.next_run_at) : "—"}</TableCell>
            <TableCell className="text-right text-xs">{task.total_run_count}</TableCell>
            <TableCell className="text-center">
              <button
                role="switch"
                aria-checked={task.enabled}
                aria-label={task.enabled ? "Disable task" : "Enable task"}
                disabled={toggle.isPending}
                onClick={() => toggle.mutate({ id: task.id, enabled: !task.enabled })}
                className={`relative inline-flex h-5 w-9 cursor-pointer rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 ${
                  task.enabled ? "bg-primary" : "bg-input"
                }`}
              >
                <span
                  className={`pointer-events-none block h-4 w-4 rounded-full bg-background shadow-lg ring-0 transition-transform ${
                    task.enabled ? "translate-x-4" : "translate-x-0"
                  }`}
                />
              </button>
            </TableCell>
            <TableCell>
              <Button
                variant="outline"
                size="sm"
                disabled={triggeredId === task.id}
                onClick={() => handleTrigger(task.id)}
              >
                {triggeredId === task.id ? "Queuing…" : "Run now"}
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
