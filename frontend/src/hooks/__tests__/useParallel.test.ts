import { describe, it, expect, vi, afterEach } from "vitest";
import { act, waitFor } from "@testing-library/react";
import { renderHookWithQuery } from "@/test/render";
import { useParallel } from "@/hooks/useParallel";

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

const RUN_ID = "33333333-3333-3333-3333-333333333333";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useParallel — initial state", () => {
  it("starts idle with no tasks or output", () => {
    const { result } = renderHookWithQuery(() => useParallel());
    expect(result.current.tasks).toEqual([]);
    expect(result.current.output).toBeNull();
    expect(result.current.tally).toBeNull();
    expect(result.current.isRunning).toBe(false);
    expect(result.current.error).toBeNull();
  });
});

describe("useParallel — sectioning", () => {
  it("started seeds running cards; task updates them; result sets output", async () => {
    mockFetchSSE([
      {
        event: "started",
        strategy: "sectioning",
        tasks: [
          { task_id: "valuation", label: "Valuation" },
          { task_id: "profitability", label: "Profitability" },
          { task_id: "risk", label: "Risk" },
        ],
      },
      { event: "task", task_id: "valuation", label: "Valuation", status: "done", output: "cheap", vote: null, error: null },
      { event: "result", strategy: "sectioning", output: "final", tally: null, run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => useParallel());

    await act(async () => {
      result.current.run("analyse AAPL", undefined, { strategy: "sectioning" });
    });

    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(result.current.tasks).toHaveLength(3);
    expect(result.current.tasks.find((t) => t.task_id === "valuation")?.status).toBe("done");
    expect(result.current.tasks.find((t) => t.task_id === "valuation")?.output).toBe("cheap");
    expect(result.current.output).toBe("final");
    expect(result.current.tally).toBeNull();
    expect(result.current.runId).toBe(RUN_ID);
  });
});

describe("useParallel — voting", () => {
  it("task events carry votes and result exposes the tally", async () => {
    mockFetchSSE([
      {
        event: "started",
        strategy: "voting",
        tasks: [
          { task_id: "vote_0", label: "Vote 1" },
          { task_id: "vote_1", label: "Vote 2" },
          { task_id: "vote_2", label: "Vote 3" },
        ],
      },
      { event: "task", task_id: "vote_0", label: "Vote 1", status: "done", output: "r", vote: "buy", error: null },
      { event: "task", task_id: "vote_1", label: "Vote 2", status: "done", output: "r", vote: "buy", error: null },
      { event: "task", task_id: "vote_2", label: "Vote 3", status: "done", output: "r", vote: "hold", error: null },
      {
        event: "result",
        strategy: "voting",
        output: "consensus",
        tally: { buy: 2, hold: 1, sell: 0 },
        run_id: RUN_ID,
      },
    ]);

    const { result } = renderHookWithQuery(() => useParallel());

    await act(async () => {
      result.current.run("buy AAPL?", undefined, { strategy: "voting", n: 3 });
    });

    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(result.current.strategy).toBe("voting");
    expect(result.current.tasks.map((t) => t.vote)).toEqual(["buy", "buy", "hold"]);
    expect(result.current.tally).toEqual({ buy: 2, hold: 1, sell: 0 });
    expect(result.current.output).toBe("consensus");
  });
});

describe("useParallel — error handling", () => {
  it("error event sets error and clears isRunning", async () => {
    mockFetchSSE([{ event: "error", error: "All vote calls failed." }]);

    const { result } = renderHookWithQuery(() => useParallel());

    await act(async () => {
      result.current.run("x", undefined, { strategy: "voting" });
    });

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.error).toContain("failed");
    expect(result.current.isRunning).toBe(false);
  });
});

describe("useParallel — reset", () => {
  it("reset clears all state", async () => {
    mockFetchSSE([
      { event: "started", strategy: "sectioning", tasks: [{ task_id: "valuation", label: "Valuation" }] },
      { event: "result", strategy: "sectioning", output: "out", tally: null, run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => useParallel());

    await act(async () => {
      result.current.run("q", undefined, { strategy: "sectioning" });
    });
    await waitFor(() => expect(result.current.output).toBe("out"));

    act(() => {
      result.current.reset();
    });
    expect(result.current.tasks).toEqual([]);
    expect(result.current.output).toBeNull();
    expect(result.current.tally).toBeNull();
  });
});
