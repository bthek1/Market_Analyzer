import { describe, it, expect, vi, afterEach } from "vitest";
import { act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderHookWithQuery } from "@/test/render";
import { MOCK_LLM_SETTINGS } from "@/test/handlers";
import { usePlanExecute } from "@/hooks/usePlanExecute";

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

const RUN_ID = "66666666-6666-6666-6666-666666666666";

function planSpec(task: string, tool: string | null = null) {
  return { task, tool, args: tool ? { symbol: "AAPL" } : null };
}

function stepEvent(order: number, task: string, tool: string | null = null) {
  return {
    event: "step",
    order,
    task,
    tool,
    args: tool ? { symbol: "AAPL" } : null,
    observation: tool ? '{"trailing_pe": 31}' : null,
    result: `result ${order}`,
    status: "done",
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("usePlanExecute — initial state", () => {
  it("starts idle with no plan, steps, or output", () => {
    const { result } = renderHookWithQuery(() => usePlanExecute());
    expect(result.current.plan).toBeNull();
    expect(result.current.steps).toEqual([]);
    expect(result.current.output).toBeNull();
    expect(result.current.replans).toBe(0);
    expect(result.current.isRunning).toBe(false);
    expect(result.current.error).toBeNull();
  });
});

describe("usePlanExecute — reflects LLM settings", () => {
  it("seeds maxSteps from the configured plan_max_steps before any run", async () => {
    server.use(
      http.get(`${BASE}/api/llm/settings/`, () =>
        HttpResponse.json({ ...MOCK_LLM_SETTINGS, plan_max_steps: 14 }),
      ),
    );
    const { result } = renderHookWithQuery(() => usePlanExecute());
    await waitFor(() => expect(result.current.maxSteps).toBe(14));
  });

  it("a run's started event overrides the configured default", async () => {
    server.use(
      http.get(`${BASE}/api/llm/settings/`, () =>
        HttpResponse.json({ ...MOCK_LLM_SETTINGS, plan_max_steps: 14 }),
      ),
    );
    mockFetchSSE([
      { event: "started", max_steps: 3, allow_replan: false },
      { event: "plan", steps: [planSpec("a")] },
      { event: "result", output: "out", steps: 1, replans: 0, run_id: RUN_ID },
    ]);
    const { result } = renderHookWithQuery(() => usePlanExecute());
    await waitFor(() => expect(result.current.maxSteps).toBe(14));

    await act(async () => {
      result.current.run("q");
    });
    await waitFor(() => expect(result.current.output).toBe("out"));
    expect(result.current.maxSteps).toBe(3);
    expect(result.current.allowReplan).toBe(false);
  });
});

describe("usePlanExecute — loop", () => {
  it("sets the plan, appends steps in order, and sets output on result", async () => {
    mockFetchSSE([
      { event: "started", max_steps: 6, allow_replan: true },
      { event: "plan", steps: [planSpec("fetch", "company_snapshot"), planSpec("write")] },
      stepEvent(0, "fetch", "company_snapshot"),
      stepEvent(1, "write"),
      { event: "result", output: "## Verdict", steps: 2, replans: 0, run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => usePlanExecute());

    await act(async () => {
      result.current.run("Is AAPL cheap?");
    });

    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(result.current.maxSteps).toBe(6);
    expect(result.current.allowReplan).toBe(true);
    expect(result.current.plan).toHaveLength(2);
    expect(result.current.steps).toHaveLength(2);
    expect(result.current.steps.map((s) => s.tool)).toEqual(["company_snapshot", null]);
    expect(result.current.steps[0].result).toBe("result 0");
    expect(result.current.output).toBe("## Verdict");
    expect(result.current.runId).toBe(RUN_ID);
  });

  it("replan event replaces the plan and bumps the replan counter", async () => {
    mockFetchSSE([
      { event: "started", max_steps: 6, allow_replan: true },
      { event: "plan", steps: [planSpec("fetch", "company_profile"), planSpec("write")] },
      stepEvent(0, "fetch", "company_profile"),
      {
        event: "replan",
        reason: "company_profile returned an error",
        steps: [planSpec("fetch", "company_profile"), planSpec("retry differently")],
      },
      stepEvent(1, "retry differently"),
      { event: "result", output: "done", steps: 2, replans: 1, run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => usePlanExecute());

    await act(async () => {
      result.current.run("q");
    });

    await waitFor(() => expect(result.current.output).toBe("done"));
    expect(result.current.replans).toBe(1);
    expect(result.current.plan?.[1].task).toBe("retry differently");
  });
});

describe("usePlanExecute — error handling", () => {
  it("error event sets error and clears isRunning", async () => {
    mockFetchSSE([
      { event: "started", max_steps: 6, allow_replan: true },
      { event: "error", error: "Planner did not return a usable plan." },
    ]);

    const { result } = renderHookWithQuery(() => usePlanExecute());

    await act(async () => {
      result.current.run("x");
    });

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.error).toContain("usable plan");
    expect(result.current.isRunning).toBe(false);
  });
});

describe("usePlanExecute — reset", () => {
  it("reset clears all state", async () => {
    mockFetchSSE([
      { event: "started", max_steps: 6, allow_replan: true },
      { event: "plan", steps: [planSpec("a")] },
      stepEvent(0, "a"),
      { event: "result", output: "out", steps: 1, replans: 0, run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => usePlanExecute());

    await act(async () => {
      result.current.run("q");
    });
    await waitFor(() => expect(result.current.output).toBe("out"));

    act(() => {
      result.current.reset();
    });
    expect(result.current.plan).toBeNull();
    expect(result.current.steps).toEqual([]);
    expect(result.current.output).toBeNull();
  });
});
