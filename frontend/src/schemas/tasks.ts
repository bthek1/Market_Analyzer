import { z } from "zod";

export const taskStatusSchema = z.enum([
  "SUCCESS",
  "FAILURE",
  "PENDING",
  "STARTED",
  "RETRY",
  "REVOKED",
]);

export const taskResultSchema = z.object({
  task_id: z.string(),
  task_name: z.string().nullable(),
  periodic_task_name: z.string().nullable(),
  status: taskStatusSchema,
  result: z.string().nullable(),
  date_created: z.string(),
  date_started: z.string().nullable(),
  date_done: z.string().nullable(),
  traceback: z.string().nullable(),
  task_args: z.string().nullable(),
  task_kwargs: z.string().nullable(),
  worker: z.string().nullable(),
});

export const periodicTaskSchema = z.object({
  id: z.number(),
  name: z.string(),
  task: z.string(),
  enabled: z.boolean(),
  interval_display: z.string(),
  last_run_at: z.string().nullable(),
  total_run_count: z.number(),
  date_changed: z.string(),
});

export const triggerResponseSchema = z.object({
  task_id: z.string(),
});
