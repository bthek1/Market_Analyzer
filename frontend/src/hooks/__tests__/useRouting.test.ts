import { describe, it, expect, vi, afterEach } from "vitest";
import { act, waitFor } from "@testing-library/react";
import { renderHookWithQuery } from "@/test/render";
import { useRouting } from "@/hooks/useRouting";

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

const RUN_ID = "22222222-2222-2222-2222-222222222222";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useRouting — initial state", () => {
  it("starts idle with no classification or output", () => {
    const { result } = renderHookWithQuery(() => useRouting());
    expect(result.current.classification).toBeNull();
    expect(result.current.route).toBeNull();
    expect(result.current.isClassifying).toBe(false);
    expect(result.current.isExecuting).toBe(false);
    expect(result.current.output).toBeNull();
    expect(result.current.error).toBeNull();
  });
});

describe("useRouting — simple route", () => {
  it("classified then result events update state correctly", async () => {
    mockFetchSSE([
      { event: "classified", route: "simple", reason: "price check", tickers: ["AAPL"], complexity: "low" },
      { event: "result", route: "simple", output: "AAPL is $200", run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => useRouting());

    await act(async () => {
      result.current.run("What is AAPL price?");
    });

    await waitFor(() => expect(result.current.isExecuting).toBe(false));
    expect(result.current.route).toBe("simple");
    expect(result.current.classification?.reason).toBe("price check");
    expect(result.current.classification?.tickers).toEqual(["AAPL"]);
    expect(result.current.output).toBe("AAPL is $200");
    expect(result.current.runId).toBe(RUN_ID);
    expect(result.current.error).toBeNull();
  });
});

describe("useRouting — deep_research route", () => {
  it("chain_step events update chainSteps and result sets output", async () => {
    mockFetchSSE([
      { event: "classified", route: "deep_research", reason: "thesis", tickers: ["AAPL"], complexity: "high" },
      { run_id: RUN_ID, step_id: "__init__", label: "", status: "running", output: null, error: null },
      { run_id: RUN_ID, step_id: "research", label: "Gather Data", status: "done", output: "[]", error: null },
      { run_id: RUN_ID, step_id: "format", label: "Format Report", status: "done", output: "# Report", error: null },
      { run_id: RUN_ID, step_id: "__done__", label: "", status: "done", output: null, error: null },
      { event: "result", route: "deep_research", output: "# Report", run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => useRouting());

    await act(async () => {
      result.current.run("Investment thesis for AAPL");
    });

    await waitFor(() => expect(result.current.isExecuting).toBe(false));
    expect(result.current.route).toBe("deep_research");

    const research = result.current.chainSteps.find((s) => s.step_id === "research");
    const format = result.current.chainSteps.find((s) => s.step_id === "format");
    expect(research?.status).toBe("done");
    expect(format?.status).toBe("done");
    expect(result.current.output).toBe("# Report");
  });
});

describe("useRouting — error handling", () => {
  it("error event sets error state and clears flags", async () => {
    mockFetchSSE([{ event: "error", error: "Classifier returned non-JSON output" }]);

    const { result } = renderHookWithQuery(() => useRouting());

    await act(async () => {
      result.current.run("garbled query");
    });

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.error).toContain("non-JSON");
    expect(result.current.isClassifying).toBe(false);
    expect(result.current.isExecuting).toBe(false);
  });
});

describe("useRouting — reset", () => {
  it("reset clears all state", async () => {
    mockFetchSSE([
      { event: "classified", route: "simple", reason: "x", tickers: [], complexity: "low" },
      { event: "result", route: "simple", output: "out", run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => useRouting());

    await act(async () => {
      result.current.run("test");
    });
    await waitFor(() => expect(result.current.output).not.toBeNull());

    act(() => {
      result.current.reset();
    });

    expect(result.current.classification).toBeNull();
    expect(result.current.route).toBeNull();
    expect(result.current.output).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.runId).toBeNull();
    expect(result.current.isClassifying).toBe(false);
    expect(result.current.isExecuting).toBe(false);
  });
});
