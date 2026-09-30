import { describe, it, expect, vi, afterEach } from "vitest";
import { act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderHookWithQuery } from "@/test/render";
import { MOCK_LLM_SETTINGS } from "@/test/handlers";
import { useAutonomous } from "@/hooks/useAutonomous";

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
    vi
      .fn()
      .mockResolvedValue({
        ok: true,
        status: 200,
        body: makeSSEStream(events),
      }),
  );
}

const RUN_ID = "88888888-8888-8888-8888-888888888888";

function cycleEvent(
  index: number,
  output: string,
  {
    action = "reason",
    tool = null,
    observation = null,
    spawned = false,
    subagent_steps = null,
    backlog = null,
    goal_complete = false,
    status = "done",
    error = null,
  }: {
    action?: string;
    tool?: string | null;
    observation?: string | null;
    spawned?: boolean;
    subagent_steps?:
      | { thought: string; tool: string; args: null; observation: string }[]
      | null;
    backlog?: string[] | null;
    goal_complete?: boolean;
    status?: string;
    error?: string | null;
  } = {},
) {
  return {
    event: "cycle",
    index,
    reflection: `reflection ${index}`,
    task: `task ${index}`,
    action,
    tool,
    args: null,
    observation,
    spawned,
    subagent_steps,
    output,
    backlog,
    goal_complete,
    status,
    error,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useAutonomous — initial state", () => {
  it("starts idle with no goal, cycles, or output", () => {
    const { result } = renderHookWithQuery(() => useAutonomous());
    expect(result.current.goal).toBeNull();
    expect(result.current.cycles).toEqual([]);
    expect(result.current.output).toBeNull();
    expect(result.current.isRunning).toBe(false);
    expect(result.current.error).toBeNull();
  });
});

describe("useAutonomous — reflects LLM settings", () => {
  it("seeds maxCycles from the configured auto_max_cycles before any run", async () => {
    server.use(
      http.get(`${BASE}/api/llm/settings/`, () =>
        HttpResponse.json({ ...MOCK_LLM_SETTINGS, auto_max_cycles: 12 }),
      ),
    );
    const { result } = renderHookWithQuery(() => useAutonomous());
    await waitFor(() => expect(result.current.maxCycles).toBe(12));
  });

  it("returns to the configured setting after reset (no permanent latch)", async () => {
    server.use(
      http.get(`${BASE}/api/llm/settings/`, () =>
        HttpResponse.json({ ...MOCK_LLM_SETTINGS, auto_max_cycles: 12 }),
      ),
    );
    mockFetchSSE([
      { event: "goal", goal: "G", backlog: [], max_cycles: 5 },
      {
        event: "result",
        output: "done",
        cycles: 0,
        stop_reason: "complete",
        run_id: RUN_ID,
      },
    ]);
    const { result } = renderHookWithQuery(() => useAutonomous());
    // Idle: mirrors the live setting.
    await waitFor(() => expect(result.current.maxCycles).toBe(12));
    // A run reports its own cap.
    await act(async () => {
      result.current.run("G");
    });
    await waitFor(() => expect(result.current.maxCycles).toBe(5));
    // Reset returns to mirroring the setting (previously the latch stuck at 5).
    act(() => {
      result.current.reset();
    });
    await waitFor(() => expect(result.current.maxCycles).toBe(12));
  });
});

describe("useAutonomous — loop", () => {
  it("goal seeds backlog; cycle events append; result sets output + stop reason", async () => {
    mockFetchSSE([
      {
        event: "goal",
        goal: "Analyse AAPL",
        backlog: ["get profile", "get snapshot"],
        max_cycles: 8,
      },
      cycleEvent(0, "analysis", {
        action: "tool",
        tool: "company_snapshot",
        observation: '{"trailing_pe": 30}',
        backlog: ["get snapshot"],
      }),
      cycleEvent(1, "", { goal_complete: true }),
      {
        event: "result",
        output: "## Final",
        cycles: 1,
        stop_reason: "complete",
        run_id: RUN_ID,
      },
    ]);

    const { result } = renderHookWithQuery(() => useAutonomous());

    await act(async () => {
      result.current.run("Analyse AAPL");
    });

    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(result.current.goal).toBe("Analyse AAPL");
    expect(result.current.cycles).toHaveLength(2);
    const c0 = result.current.cycles[0];
    expect(c0.tool).toBe("company_snapshot");
    expect(c0.observation).toBe('{"trailing_pe": 30}');
    expect(result.current.cycles[1].goal_complete).toBe(true);
    expect(result.current.output).toBe("## Final");
    expect(result.current.stopReason).toBe("complete");
    expect(result.current.runId).toBe(RUN_ID);
  });

  it("tracks a spawned sub-agent cycle", async () => {
    mockFetchSSE([
      { event: "goal", goal: "G", backlog: [], max_cycles: 8 },
      cycleEvent(0, "sub findings", {
        action: "subagent",
        spawned: true,
        subagent_steps: [
          {
            thought: "look",
            tool: "company_profile",
            args: null,
            observation: "{}",
          },
        ],
      }),
      {
        event: "result",
        output: "done",
        cycles: 1,
        stop_reason: "budget",
        run_id: RUN_ID,
      },
    ]);

    const { result } = renderHookWithQuery(() => useAutonomous());

    await act(async () => {
      result.current.run("q");
    });

    await waitFor(() => expect(result.current.output).toBe("done"));
    expect(result.current.cycles[0].spawned).toBe(true);
    expect(result.current.cycles[0].subagent_steps).toHaveLength(1);
    expect(result.current.stopReason).toBe("budget");
  });

  it("a failing cycle keeps the others and the run still completes", async () => {
    mockFetchSSE([
      { event: "goal", goal: "G", backlog: [], max_cycles: 8 },
      cycleEvent(0, "", { status: "error", error: "boom" }),
      cycleEvent(1, "good"),
      {
        event: "result",
        output: "done",
        cycles: 1,
        stop_reason: "no_progress",
        run_id: RUN_ID,
      },
    ]);

    const { result } = renderHookWithQuery(() => useAutonomous());

    await act(async () => {
      result.current.run("q");
    });

    await waitFor(() => expect(result.current.output).toBe("done"));
    expect(result.current.cycles[0].status).toBe("error");
    expect(result.current.cycles[0].error).toBe("boom");
    expect(result.current.cycles[1].status).toBe("done");
  });
});

describe("useAutonomous — error handling", () => {
  it("error event sets error and clears isRunning", async () => {
    mockFetchSSE([
      { event: "error", error: "Autonomous agent produced no usable results." },
    ]);

    const { result } = renderHookWithQuery(() => useAutonomous());

    await act(async () => {
      result.current.run("x");
    });

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.error).toContain("no usable results");
    expect(result.current.isRunning).toBe(false);
  });
});

describe("useAutonomous — reset", () => {
  it("reset clears all state", async () => {
    mockFetchSSE([
      { event: "goal", goal: "G", backlog: ["t"], max_cycles: 8 },
      cycleEvent(0, "out"),
      {
        event: "result",
        output: "out",
        cycles: 1,
        stop_reason: "budget",
        run_id: RUN_ID,
      },
    ]);

    const { result } = renderHookWithQuery(() => useAutonomous());

    await act(async () => {
      result.current.run("q");
    });
    await waitFor(() => expect(result.current.output).toBe("out"));

    act(() => {
      result.current.reset();
    });

    expect(result.current.goal).toBeNull();
    expect(result.current.cycles).toEqual([]);
    expect(result.current.output).toBeNull();
    expect(result.current.runId).toBeNull();
    expect(result.current.stopReason).toBeNull();
  });
});
