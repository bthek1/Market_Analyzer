import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { TaskStatus } from "@/types/tasks";

const STATUS_CONFIG: Record<TaskStatus, { label: string; className: string }> = {
  SUCCESS: { label: "Success", className: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400" },
  FAILURE: { label: "Failure", className: "" },
  PENDING: { label: "Pending", className: "" },
  STARTED: { label: "Started", className: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400" },
  RETRY: { label: "Retry", className: "" },
  REVOKED: { label: "Revoked", className: "bg-muted text-muted-foreground" },
};

const STATUS_VARIANT: Record<TaskStatus, "default" | "destructive" | "secondary" | "outline"> = {
  SUCCESS: "default",
  FAILURE: "destructive",
  PENDING: "secondary",
  STARTED: "default",
  RETRY: "outline",
  REVOKED: "secondary",
};

interface TaskStatusBadgeProps {
  status: TaskStatus;
}

export function TaskStatusBadge({ status }: TaskStatusBadgeProps) {
  const config = STATUS_CONFIG[status] ?? { label: status, className: "" };
  return (
    <Badge
      variant={STATUS_VARIANT[status] ?? "outline"}
      className={cn(config.className)}
    >
      {config.label}
    </Badge>
  );
}
