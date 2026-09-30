import { describe, it, expect } from "vitest";
import { act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderHookWithQuery } from "@/test/render";
import {
  useSchedules,
  useTaskResult,
  useTaskResults,
  useToggleSchedule,
  useTriggerTask,
} from "@/hooks/useTasks";
import {
  MOCK_PAGINATED_TASK_RESULTS,
  MOCK_PERIODIC_TASK,
  MOCK_TASK_RESULT,
} from "@/test/handlers";

const BASE = "http://localhost:8004";

describe("useTaskResults", () => {
  it("returns paginated task results", async () => {
    server.use(
      http.get(`${BASE}/api/tasks/results/`, () =>
        HttpResponse.json(MOCK_PAGINATED_TASK_RESULTS),
      ),
    );
    const { result } = renderHookWithQuery(() => useTaskResults());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.count).toBe(2);
    expect(result.current.data?.results[0].task_id).toBe(MOCK_TASK_RESULT.task_id);
  });

  it("passes status filter as query param", async () => {
    let capturedUrl = "";
    server.use(
      http.get(`${BASE}/api/tasks/results/`, ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json({ count: 1, next: null, previous: null, results: [MOCK_TASK_RESULT] });
      }),
    );
    const { result } = renderHookWithQuery(() => useTaskResults("SUCCESS"));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedUrl).toContain("status=SUCCESS");
  });
});

describe("useTaskResult", () => {
  it("returns a single task result by id", async () => {
    server.use(
      http.get(`${BASE}/api/tasks/results/:taskId/`, () =>
        HttpResponse.json(MOCK_TASK_RESULT),
      ),
    );
    const { result } = renderHookWithQuery(() => useTaskResult(MOCK_TASK_RESULT.task_id));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.status).toBe("SUCCESS");
  });

  it("stays idle when taskId is empty", () => {
    const { result } = renderHookWithQuery(() => useTaskResult(""));
    expect(result.current.fetchStatus).toBe("idle");
  });
});

describe("useSchedules", () => {
  it("returns list of periodic tasks", async () => {
    server.use(
      http.get(`${BASE}/api/tasks/schedules/`, () =>
        HttpResponse.json([MOCK_PERIODIC_TASK]),
      ),
    );
    const { result } = renderHookWithQuery(() => useSchedules());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.[0].name).toBe("yfinance-sync-company-profiles-daily");
  });
});

describe("useToggleSchedule", () => {
  it("calls PATCH and returns updated task", async () => {
    server.use(
      http.patch(`${BASE}/api/tasks/schedules/:id/`, async ({ request }) => {
        const body = await request.json() as { enabled: boolean };
        return HttpResponse.json({ ...MOCK_PERIODIC_TASK, enabled: body.enabled });
      }),
    );
    const { result } = renderHookWithQuery(() => useToggleSchedule());
    act(() => {
      result.current.mutate({ id: 1, enabled: false });
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.enabled).toBe(false);
  });

  it("is error on 404", async () => {
    server.use(
      http.patch(`${BASE}/api/tasks/schedules/:id/`, () =>
        HttpResponse.json({ detail: "Not found." }, { status: 404 }),
      ),
    );
    const { result } = renderHookWithQuery(() => useToggleSchedule());
    act(() => {
      result.current.mutate({ id: 99999, enabled: false });
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useTriggerTask", () => {
  it("returns new task_id on success", async () => {
    server.use(
      http.post(`${BASE}/api/tasks/schedules/:id/trigger/`, () =>
        HttpResponse.json({ task_id: "new-task-uuid" }, { status: 202 }),
      ),
    );
    const { result } = renderHookWithQuery(() => useTriggerTask());
    act(() => {
      result.current.mutate(1);
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.task_id).toBe("new-task-uuid");
  });

  it("is error on 404", async () => {
    server.use(
      http.post(`${BASE}/api/tasks/schedules/:id/trigger/`, () =>
        HttpResponse.json({ detail: "Not found." }, { status: 404 }),
      ),
    );
    const { result } = renderHookWithQuery(() => useTriggerTask());
    act(() => {
      result.current.mutate(99999);
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
