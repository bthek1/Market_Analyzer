import { describe, it, expect } from "vitest";
import {
  periodicTaskSchema,
  taskResultSchema,
  taskStatusSchema,
  triggerResponseSchema,
} from "@/schemas/tasks";

describe("taskStatusSchema", () => {
  const valid = ["SUCCESS", "FAILURE", "PENDING", "STARTED", "RETRY", "REVOKED"] as const;

  for (const status of valid) {
    it(`accepts ${status}`, () => {
      expect(taskStatusSchema.parse(status)).toBe(status);
    });
  }

  it("rejects unknown status", () => {
    expect(() => taskStatusSchema.parse("UNKNOWN")).toThrow();
  });
});

describe("taskResultSchema", () => {
  const valid = {
    task_id: "aaaa-bbbb",
    task_name: "apps.companies.tasks.sync_company_profiles",
    periodic_task_name: null,
    status: "SUCCESS" as const,
    result: '{"created": 1}',
    date_created: "2026-05-28T10:00:00Z",
    date_started: "2026-05-28T10:00:01Z",
    date_done: "2026-05-28T10:00:03Z",
    traceback: null,
    task_args: "[]",
    task_kwargs: "{}",
    worker: "celery@prod",
  };

  it("parses a valid task result", () => {
    expect(taskResultSchema.parse(valid)).toMatchObject({ task_id: "aaaa-bbbb" });
  });

  it("accepts null nullable fields", () => {
    const result = taskResultSchema.parse({
      ...valid,
      task_name: null,
      periodic_task_name: null,
      traceback: null,
      date_started: null,
      date_done: null,
      task_args: null,
      task_kwargs: null,
      worker: null,
    });
    expect(result.traceback).toBeNull();
    expect(result.worker).toBeNull();
  });

  it("rejects missing task_id", () => {
    const { task_id: _, ...rest } = valid;
    expect(() => taskResultSchema.parse(rest)).toThrow();
  });

  it("rejects invalid status", () => {
    expect(() => taskResultSchema.parse({ ...valid, status: "NOPE" })).toThrow();
  });
});

describe("periodicTaskSchema", () => {
  const valid = {
    id: 1,
    name: "yfinance-sync-company-profiles-daily",
    task: "apps.companies.tasks.sync_company_profiles",
    enabled: true,
    interval_display: "every 24 hours",
    last_run_at: null,
    total_run_count: 0,
    date_changed: "2026-05-28T00:00:00Z",
  };

  it("parses a valid periodic task", () => {
    expect(periodicTaskSchema.parse(valid)).toMatchObject({ id: 1, enabled: true });
  });

  it("accepts null last_run_at", () => {
    expect(periodicTaskSchema.parse(valid).last_run_at).toBeNull();
  });

  it("rejects non-boolean enabled", () => {
    expect(() => periodicTaskSchema.parse({ ...valid, enabled: "yes" })).toThrow();
  });

  it("rejects missing name", () => {
    const { name: _, ...rest } = valid;
    expect(() => periodicTaskSchema.parse(rest)).toThrow();
  });
});

describe("triggerResponseSchema", () => {
  it("parses valid response", () => {
    expect(triggerResponseSchema.parse({ task_id: "new-uuid" })).toEqual({
      task_id: "new-uuid",
    });
  });

  it("rejects missing task_id", () => {
    expect(() => triggerResponseSchema.parse({})).toThrow();
  });
});
