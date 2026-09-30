import { describe, it, expect, vi, afterEach } from "vitest";
import { act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderHookWithQuery } from "@/test/render";
import { MOCK_LLM_SETTINGS } from "@/test/handlers";
import { useReact } from "@/hooks/useReact";

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

const RUN_ID = "44444444-4444-4444-4444-444444444444";

function actionEvent(order: number, tool: string, args: object) {
  return {
    event: "step",
    id: `row-${order}`,
    order,
    thought: `calling ${tool}`,
    tool,
    tool_args: args,
    observation: "{}",
    is_answer: false,
    status: "done",
    error: null,
  };
}

function answerEvent(order: number) {
  return {
    event: "step",
    id: `row-${order}`,
    order,
    thought: "done reasoning",
    tool: "",
    tool_args: null,
    observation: "",
    is_answer: true,
    status: "done",
    error: null,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useReact — initial state", () => {
  it("starts idle with no steps or output", () => {
    const { result } = renderHookWithQuery(() => useReact());
    expect(result.current.steps).toEqual([]);
    expect(result.current.output).toBeNull();
    expect(result.current.isRunning).toBe(false);
    expect(result.current.error).toBeNull();
  });
});

describe("useReact — loop", () => {
  it("appends each step in order and sets output on result", async () => {
    mockFetchSSE([
      { event: "started", max_steps: 6, tools: ["company_snapshot"] },
      actionEvent(0, "company_snapshot", { symbol: "AAPL" }),
      actionEvent(1, "recent_price", { symbol: "AAPL" }),
      answerEvent(2),
      { event: "result", output: "AAPL looks cheap", run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => useReact());

    await act(async () => {
      result.current.run("Is AAPL cheap?");
    });

    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(result.current.maxSteps).toBe(6);
    expect(result.current.steps).toHaveLength(3);
    // The answer step has no tool: "" rather than null, matching the row's
    // representation on both the live stream and a refresh-restore.
    expect(result.current.steps.map((s) => s.tool)).toEqual([
      "company_snapshot",
      "recent_price",
      "",
    ]);
    expect(result.current.steps[0].tool_args).toEqual({ symbol: "AAPL" });
    expect(result.current.steps[2].is_answer).toBe(true);
    expect(result.current.output).toBe("AAPL looks cheap");
    expect(result.current.runId).toBe(RUN_ID);
  });
});

describe("useReact — settings-driven cap", () => {
  it("mirrors react_max_steps from LLM settings before any run", async () => {
    server.use(
      http.get(`${BASE}/api/llm/settings/`, () =>
        HttpResponse.json({ ...MOCK_LLM_SETTINGS, react_max_steps: 9 })),
    );
    const { result } = renderHookWithQuery(() => useReact());
    await waitFor(() => expect(result.current.maxSteps).toBe(9));
  });

  it("the run's started cap overrides the settings default", async () => {
    server.use(
      http.get(`${BASE}/api/llm/settings/`, () =>
        HttpResponse.json({ ...MOCK_LLM_SETTINGS, react_max_steps: 9 })),
    );
    mockFetchSSE([
      { event: "started", max_steps: 4, tools: [] },
      answerEvent(0),
      { event: "result", output: "done", run_id: RUN_ID },
    ]);
    const { result } = renderHookWithQuery(() => useReact());
    await waitFor(() => expect(result.current.maxSteps).toBe(9));

    await act(async () => {
      result.current.run("q");
    });
    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(result.current.maxSteps).toBe(4);
  });
});

describe("useReact — error handling", () => {
  it("error event sets error and clears isRunning", async () => {
    mockFetchSSE([
      { event: "started", max_steps: 6, tools: [] },
      { event: "error", error: "Ollama is down" },
    ]);

    const { result } = renderHookWithQuery(() => useReact());

    await act(async () => {
      result.current.run("x");
    });

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.error).toContain("down");
    expect(result.current.isRunning).toBe(false);
  });
});

describe("useReact — reset", () => {
  it("reset clears all state", async () => {
    mockFetchSSE([
      { event: "started", max_steps: 6, tools: [] },
      actionEvent(0, "company_profile", { symbol: "AAPL" }),
      answerEvent(1),
      { event: "result", output: "out", run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => useReact());

    await act(async () => {
      result.current.run("q");
    });
    await waitFor(() => expect(result.current.output).toBe("out"));

    act(() => {
      result.current.reset();
    });
    expect(result.current.steps).toEqual([]);
    expect(result.current.output).toBeNull();
  });
});
