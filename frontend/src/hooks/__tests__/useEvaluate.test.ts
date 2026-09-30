import { describe, it, expect, vi, afterEach } from "vitest";
import { act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderHookWithQuery } from "@/test/render";
import { MOCK_LLM_SETTINGS } from "@/test/handlers";
import { useEvaluate } from "@/hooks/useEvaluate";

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

const RUN_ID = "55555555-5555-5555-5555-555555555555";

function iterationEvent(order: number, score: number, passed: boolean, draft = `draft${order}`) {
  return {
    event: "iteration",
    order,
    draft,
    score,
    feedback: passed ? "looks good" : "needs more detail",
    passed,
    status: "done",
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useEvaluate — initial state", () => {
  it("starts idle with no draft, iterations, or output", () => {
    const { result } = renderHookWithQuery(() => useEvaluate());
    expect(result.current.draft).toBeNull();
    expect(result.current.iterations).toEqual([]);
    expect(result.current.output).toBeNull();
    expect(result.current.bestScore).toBeNull();
    expect(result.current.isRunning).toBe(false);
    expect(result.current.error).toBeNull();
  });
});

describe("useEvaluate — reflects LLM settings", () => {
  it("seeds maxIterations and threshold from settings before any run", async () => {
    server.use(
      http.get(`${BASE}/api/llm/settings/`, () =>
        HttpResponse.json({
          ...MOCK_LLM_SETTINGS,
          eval_max_iterations: 5,
          eval_threshold: 9,
        })),
    );
    const { result } = renderHookWithQuery(() => useEvaluate());
    await waitFor(() => expect(result.current.maxIterations).toBe(5));
    expect(result.current.threshold).toBe(9);
  });

  it("the run's started values override the settings defaults", async () => {
    server.use(
      http.get(`${BASE}/api/llm/settings/`, () =>
        HttpResponse.json({
          ...MOCK_LLM_SETTINGS,
          eval_max_iterations: 5,
          eval_threshold: 9,
        })),
    );
    mockFetchSSE([
      { event: "started", max_iterations: 2, threshold: 7 },
      { event: "draft", draft: "d0" },
      iterationEvent(0, 8, true),
      { event: "result", output: "final", iterations: 1, best_score: 8, run_id: RUN_ID },
    ]);
    const { result } = renderHookWithQuery(() => useEvaluate());
    await waitFor(() => expect(result.current.threshold).toBe(9));

    await act(async () => {
      result.current.run("q");
    });
    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(result.current.maxIterations).toBe(2);
    expect(result.current.threshold).toBe(7);
  });
});

describe("useEvaluate — loop", () => {
  it("sets draft, appends iterations in order, and sets output + bestScore on result", async () => {
    mockFetchSSE([
      { event: "started", max_iterations: 3, threshold: 8 },
      { event: "draft", draft: "first draft" },
      iterationEvent(0, 5, false, "first draft"),
      iterationEvent(1, 9, true, "revised draft"),
      { event: "result", output: "revised draft", iterations: 2, best_score: 9, run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => useEvaluate());

    await act(async () => {
      result.current.run("Is AAPL cheap?");
    });

    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(result.current.maxIterations).toBe(3);
    expect(result.current.threshold).toBe(8);
    expect(result.current.draft).toBe("first draft");
    expect(result.current.iterations).toHaveLength(2);
    expect(result.current.iterations.map((i) => i.score)).toEqual([5, 9]);
    expect(result.current.iterations[1].passed).toBe(true);
    expect(result.current.output).toBe("revised draft");
    expect(result.current.bestScore).toBe(9);
    expect(result.current.runId).toBe(RUN_ID);
  });
});

describe("useEvaluate — error handling", () => {
  it("error event sets error and clears isRunning", async () => {
    mockFetchSSE([
      { event: "started", max_iterations: 3, threshold: 8 },
      { event: "error", error: "Ollama is down" },
    ]);

    const { result } = renderHookWithQuery(() => useEvaluate());

    await act(async () => {
      result.current.run("x");
    });

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.error).toContain("down");
    expect(result.current.isRunning).toBe(false);
  });
});

describe("useEvaluate — reset", () => {
  it("reset clears all state", async () => {
    mockFetchSSE([
      { event: "started", max_iterations: 3, threshold: 8 },
      { event: "draft", draft: "d" },
      iterationEvent(0, 9, true),
      { event: "result", output: "out", iterations: 1, best_score: 9, run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => useEvaluate());

    await act(async () => {
      result.current.run("q");
    });
    await waitFor(() => expect(result.current.output).toBe("out"));

    act(() => {
      result.current.reset();
    });
    expect(result.current.draft).toBeNull();
    expect(result.current.iterations).toEqual([]);
    expect(result.current.output).toBeNull();
    expect(result.current.bestScore).toBeNull();
  });
});
