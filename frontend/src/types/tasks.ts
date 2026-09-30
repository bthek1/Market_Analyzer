export type TaskStatus =
  | "SUCCESS"
  | "FAILURE"
  | "PENDING"
  | "STARTED"
  | "RETRY"
  | "REVOKED";

export interface TaskResult {
  task_id: string;
  task_name: string | null;
  periodic_task_name: string | null;
  status: TaskStatus;
  result: string | null;
  date_created: string;
  date_started: string | null;
  date_done: string | null;
  traceback: string | null;
  task_args: string | null;
  task_kwargs: string | null;
  worker: string | null;
}

export interface PeriodicTask {
  id: number;
  name: string;
  task: string;
  enabled: boolean;
  interval_display: string;
  last_run_at: string | null;
  next_run_at: string | null;
  total_run_count: number;
  date_changed: string;
}

export interface TriggerResponse {
  task_id: string;
}
