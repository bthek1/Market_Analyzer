import { describe, it, expect, vi, afterEach } from "vitest";
import { act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderHookWithQuery } from "@/test/render";
import { MOCK_LLM_SETTINGS } from "@/test/handlers";
import { useOrchestrator } from "@/hooks/useOrchestrator";

const BASE = "http://localhost:8004";

function makeSSEStream(events: object[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const evt of events) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(evt)}\n\n`));
      }
      controller.close();
    },
  });
}

function mockFetchSSE(events: object[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, status: 200, body: makeSSEStream(events) }),
  );
}

const RUN_ID = "77777777-7777-7777-7777-777777777777";

function subtask(task: string, focus: string, tool: string | null = null) {
  return { task, focus, tool, args: tool ? { symbol: "AAPL" } : null };
}

function workerEvent(
  order: number,
  worker_id: string,
  output: string,
  tool: string | null = null,
  status = "done",
  error: string | null = null,
) {
  return {
    event: "worker",
    worker_id,
    label: worker_id,
    order,
    task: `task ${order}`,
    tool,
    args: tool ? { symbol: "AAPL" } : null,
    observation: tool ? '{"trailing_pe": 31}' : null,
    output,
    status,
    error,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useOrchestrator — initial state", () => {
  it("starts idle with no plan, workers, or output", () => {
    const { result } = renderHookWithQuery(() => useOrchestrator());
    expect(result.current.plan).toBeNull();
    expect(result.current.workers).toEqual([]);
    expect(result.current.output).toBeNull();
    expect(result.current.isRunning).toBe(false);
    expect(result.current.error).toBeNull();
  });
});

describe("useOrchestrator — reflects LLM settings", () => {
  it("seeds maxWorkers from the configured orch_max_workers before any run", async () => {
    server.use(
      http.get(`${BASE}/api/llm/settings/`, () =>
        HttpResponse.json({ ...MOCK_LLM_SETTINGS, orch_max_workers: 6 }),
      ),
    );
    const { result } = renderHookWithQuery(() => useOrchestrator());
    await waitFor(() => expect(result.current.maxWorkers).toBe(6));
  });

  it("a run's started event overrides the configured default and clears state", async () => {
    server.use(
      http.get(`${BASE}/api/llm/settings/`, () =>
        HttpResponse.json({ ...MOCK_LLM_SETTINGS, orch_max_workers: 6 }),
      ),
    );
    mockFetchSSE([
      { event: "started", max_workers: 3 },
      { event: "plan", subtasks: [subtask("a", "fa")] },
      workerEvent(0, "fa", "out a"),
      { event: "result", output: "out", workers: 1, run_id: RUN_ID },
    ]);
    const { result } = renderHookWithQuery(() => useOrchestrator());
    await waitFor(() => expect(result.current.maxWorkers).toBe(6));

    await act(async () => {
      result.current.run("q");
    });
    await waitFor(() => expect(result.current.output).toBe("out"));
    expect(result.current.maxWorkers).toBe(3);
  });
});

describe("useOrchestrator — loop", () => {
  it("plan seeds workers, worker events upsert them, result sets output", async () => {
    mockFetchSSE([
      { event: "started", max_workers: 4 },
      {
        event: "plan",
        subtasks: [
          subtask("Aggregate sector", "valuation", "sector_analysis"),
          subtask("Assess risk", "risk"),
        ],
      },
      workerEvent(0, "valuation", "val out", "sector_analysis"),
      workerEvent(1, "risk", "risk out"),
      { event: "result", output: "## Verdict", workers: 2, run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => useOrchestrator());

    await act(async () => {
      result.current.run("Give me a full picture of AAPL");
    });

    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(result.current.maxWorkers).toBe(4);
    expect(result.current.plan).toHaveLength(2);
    expect(result.current.workers).toHaveLength(2);
    expect(result.current.workers.map((w) => w.status)).toEqual(["done", "done"]);
    expect(result.current.workers[0].output).toBe("val out");
    expect(result.current.workers[0].tool).toBe("sector_analysis");
    expect(result.current.output).toBe("## Verdict");
    expect(result.current.runId).toBe(RUN_ID);
  });

  it("plan seeds pending placeholders before worker events arrive", async () => {
    mockFetchSSE([
      { event: "started", max_workers: 4 },
      { event: "plan", subtasks: [subtask("a", "fa"), subtask("b", "fb")] },
    ]);

    const { result } = renderHookWithQuery(() => useOrchestrator());

    await act(async () => {
      result.current.run("q");
    });

    await waitFor(() => expect(result.current.workers).toHaveLength(2));
    expect(result.current.workers.map((w) => w.status)).toEqual(["pending", "pending"]);
  });

  it("a failing worker keeps the others and the run still completes", async () => {
    mockFetchSSE([
      { event: "started", max_workers: 4 },
      { event: "plan", subtasks: [subtask("a", "fa"), subtask("b", "fb")] },
      workerEvent(0, "fa", "good"),
      workerEvent(1, "fb", "", null, "error", "boom"),
      { event: "result", output: "done", workers: 2, run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => useOrchestrator());

    await act(async () => {
      result.current.run("q");
    });

    await waitFor(() => expect(result.current.output).toBe("done"));
    expect(result.current.workers[0].status).toBe("done");
    expect(result.current.workers[1].status).toBe("error");
    expect(result.current.workers[1].error).toBe("boom");
  });
});

describe("useOrchestrator — error handling", () => {
  it("error event sets error and clears isRunning", async () => {
    mockFetchSSE([
      { event: "started", max_workers: 4 },
      { event: "error", error: "Orchestrator did not return a usable decomposition." },
    ]);

    const { result } = renderHookWithQuery(() => useOrchestrator());

    await act(async () => {
      result.current.run("x");
    });

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.error).toContain("usable decomposition");
    expect(result.current.isRunning).toBe(false);
  });
});

describe("useOrchestrator — reset", () => {
  it("reset clears all state", async () => {
    mockFetchSSE([
      { event: "started", max_workers: 4 },
      { event: "plan", subtasks: [subtask("a", "fa")] },
      workerEvent(0, "fa", "out a"),
      { event: "result", output: "out", workers: 1, run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => useOrchestrator());

    await act(async () => {
      result.current.run("q");
    });
    await waitFor(() => expect(result.current.output).toBe("out"));

    act(() => {
      result.current.reset();
    });

    expect(result.current.plan).toBeNull();
    expect(result.current.workers).toEqual([]);
    expect(result.current.output).toBeNull();
    expect(result.current.runId).toBeNull();
  });
});
