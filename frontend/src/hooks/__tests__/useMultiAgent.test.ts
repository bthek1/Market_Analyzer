import { describe, it, expect, vi, afterEach } from "vitest";
import { act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderHookWithQuery } from "@/test/render";
import { MOCK_LLM_SETTINGS } from "@/test/handlers";
import { useMultiAgent } from "@/hooks/useMultiAgent";

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

const RUN_ID = "88888888-8888-8888-8888-888888888888";

function stepEvent(
  order: number,
  agent_id: string,
  output: string,
  toolCalls: object[] | null = null,
  status = "done",
  error: string | null = null,
) {
  return {
    event: "step",
    agent_id,
    label: agent_id.charAt(0).toUpperCase() + agent_id.slice(1),
    order,
    input: `handoff ${order}`,
    tool_calls: toolCalls,
    output,
    status,
    error,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useMultiAgent — initial state", () => {
  it("starts idle with no agents, steps, or output", () => {
    const { result } = renderHookWithQuery(() => useMultiAgent());
    expect(result.current.agents).toBeNull();
    expect(result.current.steps).toEqual([]);
    expect(result.current.output).toBeNull();
    expect(result.current.isRunning).toBe(false);
    expect(result.current.error).toBeNull();
  });
});

describe("useMultiAgent — reflects LLM settings", () => {
  it("seeds maxTools from the configured multiagent_max_tools before any run", async () => {
    server.use(
      http.get(`${BASE}/api/llm/settings/`, () =>
        HttpResponse.json({ ...MOCK_LLM_SETTINGS, multiagent_max_tools: 7 }),
      ),
    );
    const { result } = renderHookWithQuery(() => useMultiAgent());
    await waitFor(() => expect(result.current.maxTools).toBe(7));
  });
});

describe("useMultiAgent — loop", () => {
  it("route seeds pending steps, step events upsert them, result sets output", async () => {
    mockFetchSSE([
      { event: "route", agents: ["researcher", "analyst", "writer"], reason: "needs data" },
      stepEvent(0, "researcher", "research out", [
        { tool: "company_snapshot", args: { symbol: "AAPL" }, observation: '{"trailing_pe": 30}' },
      ]),
      stepEvent(1, "analyst", "analysis out"),
      stepEvent(2, "writer", "writer out"),
      { event: "result", output: "## Final", agents: 3, run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => useMultiAgent());

    await act(async () => {
      result.current.run("Give me a full picture of AAPL");
    });

    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(result.current.agents).toEqual(["researcher", "analyst", "writer"]);
    expect(result.current.reason).toBe("needs data");
    expect(result.current.steps).toHaveLength(3);
    expect(result.current.steps.map((s) => s.status)).toEqual(["done", "done", "done"]);
    expect(result.current.steps[0].tool_calls).toHaveLength(1);
    expect(result.current.steps[1].tool_calls).toBeNull();
    expect(result.current.output).toBe("## Final");
    expect(result.current.runId).toBe(RUN_ID);
  });

  it("route seeds pending placeholders before step events arrive", async () => {
    mockFetchSSE([
      { event: "route", agents: ["researcher", "writer"], reason: null },
    ]);

    const { result } = renderHookWithQuery(() => useMultiAgent());

    await act(async () => {
      result.current.run("q");
    });

    await waitFor(() => expect(result.current.steps).toHaveLength(2));
    expect(result.current.steps.map((s) => s.status)).toEqual(["pending", "pending"]);
    expect(result.current.steps.map((s) => s.agent_id)).toEqual(["researcher", "writer"]);
  });

  it("a failing stage keeps the others and the run still completes", async () => {
    mockFetchSSE([
      { event: "route", agents: ["analyst", "writer"], reason: null },
      stepEvent(0, "analyst", "", null, "error", "boom"),
      stepEvent(1, "writer", "writer out"),
      { event: "result", output: "done", agents: 2, run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => useMultiAgent());

    await act(async () => {
      result.current.run("q");
    });

    await waitFor(() => expect(result.current.output).toBe("done"));
    expect(result.current.steps[0].status).toBe("error");
    expect(result.current.steps[0].error).toBe("boom");
    expect(result.current.steps[1].status).toBe("done");
  });
});

describe("useMultiAgent — error handling", () => {
  it("error event sets error and clears isRunning", async () => {
    mockFetchSSE([{ event: "error", error: "All sub-agents failed." }]);

    const { result } = renderHookWithQuery(() => useMultiAgent());

    await act(async () => {
      result.current.run("x");
    });

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.error).toContain("sub-agents failed");
    expect(result.current.isRunning).toBe(false);
  });
});

describe("useMultiAgent — reset", () => {
  it("reset clears all state", async () => {
    mockFetchSSE([
      { event: "route", agents: ["writer"], reason: null },
      stepEvent(0, "writer", "out"),
      { event: "result", output: "out", agents: 1, run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => useMultiAgent());

    await act(async () => {
      result.current.run("q");
    });
    await waitFor(() => expect(result.current.output).toBe("out"));

    act(() => {
      result.current.reset();
    });

    expect(result.current.agents).toBeNull();
    expect(result.current.steps).toEqual([]);
    expect(result.current.output).toBeNull();
    expect(result.current.runId).toBeNull();
  });
});
