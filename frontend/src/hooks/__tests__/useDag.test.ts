import { describe, it, expect, vi, afterEach } from "vitest";
import { act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderHookWithQuery } from "@/test/render";
import { MOCK_LLM_SETTINGS } from "@/test/handlers";
import { useDag } from "@/hooks/useDag";

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

const RUN_ID = "99999999-9999-9999-9999-999999999999";

function planNode(
  id: string,
  wave: number,
  depends_on: string[] = [],
  tool: string | null = null,
) {
  return { id, task: `task ${id}`, focus: id.toUpperCase(), tool, args: null, depends_on, wave };
}

function nodeEvent(
  id: string,
  wave: number,
  output: string,
  depends_on: string[] = [],
  status = "done",
  error: string | null = null,
  tool: string | null = null,
  observation: string | null = null,
) {
  return {
    // "id" is the AgentStep row uuid; "node_id" is the graph node key. The wire shape
    // is the row's detail representation, so both are present and distinct.
    event: "node",
    id: `row-${id}`,
    node_id: id,
    label: id.toUpperCase(),
    wave,
    order: 0,
    task: `task ${id}`,
    tool,
    tool_args: null,
    observation,
    depends_on,
    output,
    status,
    error,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useDag — initial state", () => {
  it("starts idle with no nodes, waves, or output", () => {
    const { result } = renderHookWithQuery(() => useDag());
    expect(result.current.nodes).toEqual([]);
    expect(result.current.waves).toBeNull();
    expect(result.current.output).toBeNull();
    expect(result.current.isRunning).toBe(false);
    expect(result.current.error).toBeNull();
  });
});

describe("useDag — reflects LLM settings", () => {
  it("seeds maxNodes from the configured dag_max_nodes before any run", async () => {
    server.use(
      http.get(`${BASE}/api/llm/settings/`, () =>
        HttpResponse.json({ ...MOCK_LLM_SETTINGS, dag_max_nodes: 9 }),
      ),
    );
    const { result } = renderHookWithQuery(() => useDag());
    await waitFor(() => expect(result.current.maxNodes).toBe(9));
  });
});

describe("useDag — loop", () => {
  it("plan seeds waves + pending nodes, node events upsert them, result sets output", async () => {
    mockFetchSSE([
      {
        event: "plan",
        nodes: [planNode("a", 0), planNode("b", 0), planNode("c", 1, ["a", "b"])],
        waves: [["a", "b"], ["c"]],
      },
      { event: "wave", index: 0, node_ids: ["a", "b"] },
      nodeEvent("a", 0, "out a", [], "done", null, "company_snapshot", '{"trailing_pe": 30}'),
      nodeEvent("b", 0, "out b"),
      { event: "wave", index: 1, node_ids: ["c"] },
      nodeEvent("c", 1, "out c", ["a", "b"]),
      { event: "result", output: "## Final", nodes: 3, waves: 2, run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => useDag());

    await act(async () => {
      result.current.run("Compare AAPL and MSFT");
    });

    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(result.current.waves).toEqual([["a", "b"], ["c"]]);
    expect(result.current.nodes).toHaveLength(3);
    expect(result.current.nodes.map((n) => n.status)).toEqual(["done", "done", "done"]);
    const c = result.current.nodes.find((n) => n.node_id === "c")!;
    expect(c.depends_on).toEqual(["a", "b"]);
    const a = result.current.nodes.find((n) => n.node_id === "a")!;
    expect(a.tool).toBe("company_snapshot");
    expect(a.observation).toBe('{"trailing_pe": 30}');
    expect(result.current.output).toBe("## Final");
    expect(result.current.runId).toBe(RUN_ID);
  });

  it("plan seeds pending placeholders; wave event flips its nodes to running", async () => {
    mockFetchSSE([
      {
        event: "plan",
        nodes: [planNode("a", 0), planNode("b", 1, ["a"])],
        waves: [["a"], ["b"]],
      },
      { event: "wave", index: 0, node_ids: ["a"] },
    ]);

    const { result } = renderHookWithQuery(() => useDag());

    await act(async () => {
      result.current.run("q");
    });

    await waitFor(() => expect(result.current.nodes).toHaveLength(2));
    const a = result.current.nodes.find((n) => n.node_id === "a")!;
    const b = result.current.nodes.find((n) => n.node_id === "b")!;
    expect(a.status).toBe("running");
    expect(b.status).toBe("pending");
  });

  it("a failing node keeps the others and the run still completes", async () => {
    mockFetchSSE([
      { event: "plan", nodes: [planNode("a", 0), planNode("b", 0)], waves: [["a", "b"]] },
      { event: "wave", index: 0, node_ids: ["a", "b"] },
      nodeEvent("a", 0, "", [], "error", "boom"),
      nodeEvent("b", 0, "out b"),
      { event: "result", output: "done", nodes: 2, waves: 1, run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => useDag());

    await act(async () => {
      result.current.run("q");
    });

    await waitFor(() => expect(result.current.output).toBe("done"));
    const a = result.current.nodes.find((n) => n.node_id === "a")!;
    const b = result.current.nodes.find((n) => n.node_id === "b")!;
    expect(a.status).toBe("error");
    expect(a.error).toBe("boom");
    expect(b.status).toBe("done");
  });
});

describe("useDag — error handling", () => {
  it("error event sets error and clears isRunning", async () => {
    mockFetchSSE([{ event: "error", error: "All nodes failed." }]);

    const { result } = renderHookWithQuery(() => useDag());

    await act(async () => {
      result.current.run("x");
    });

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.error).toContain("nodes failed");
    expect(result.current.isRunning).toBe(false);
  });
});

describe("useDag — reset", () => {
  it("reset clears all state", async () => {
    mockFetchSSE([
      { event: "plan", nodes: [planNode("a", 0)], waves: [["a"]] },
      { event: "wave", index: 0, node_ids: ["a"] },
      nodeEvent("a", 0, "out"),
      { event: "result", output: "out", nodes: 1, waves: 1, run_id: RUN_ID },
    ]);

    const { result } = renderHookWithQuery(() => useDag());

    await act(async () => {
      result.current.run("q");
    });
    await waitFor(() => expect(result.current.output).toBe("out"));

    act(() => {
      result.current.reset();
    });

    expect(result.current.nodes).toEqual([]);
    expect(result.current.waves).toBeNull();
    expect(result.current.output).toBeNull();
    expect(result.current.runId).toBeNull();
  });
});
