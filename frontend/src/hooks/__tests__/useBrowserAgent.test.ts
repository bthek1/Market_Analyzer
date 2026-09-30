import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderHookWithQuery } from "@/test/render";
import { useBrowserAgent } from "@/hooks/useBrowserAgent";

const BASE = "http://localhost:8004";
const RUN_ID = "77777777-7777-7777-7777-777777777777";

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
      .mockResolvedValue({ ok: true, status: 200, body: makeSSEStream(events) }),
  );
}

function mockFetchStatus(status: number, body: object) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      status,
      json: () => Promise.resolve(body),
    }),
  );
}

function stepEvent(order: number) {
  return {
    event: "step",
    order,
    action: "go_to_url",
    args: { url: `https://example.com/${order}` },
    url: `https://example.com/${order}`,
    title: `Page ${order}`,
    evaluation: "looks right",
    goal: `goal ${order}`,
    screenshot: `${RUN_ID}/${order}.png`,
    status: "done",
  };
}

const RESULT_EVENT = {
  event: "result",
  output: "## Answer\nNVIDIA.",
  sources: ["https://example.com/0"],
  stop_reason: "complete",
  steps: 2,
  run_id: RUN_ID,
};

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("useBrowserAgent", () => {
  it("streams steps then the answer", async () => {
    mockFetchSSE([
      {
        event: "started",
        max_steps: 15,
        provider: "anthropic",
        allowed_domains: ["*.sec.gov"],
        timeout_s: 300,
      },
      stepEvent(0),
      stepEvent(1),
      RESULT_EVENT,
    ]);

    const { result } = renderHookWithQuery(() => useBrowserAgent());
    act(() => result.current.run("who makes GPUs?"));

    await waitFor(() => expect(result.current.output).toBeTruthy());
    expect(result.current.maxSteps).toBe(15);
    expect(result.current.steps.map((s) => s.order)).toEqual([0, 1]);
    expect(result.current.steps[0].action).toBe("go_to_url");
    expect(result.current.steps[0].url).toBe("https://example.com/0");
    expect(result.current.sources).toEqual(["https://example.com/0"]);
    expect(result.current.stopReason).toBe("complete");
    expect(result.current.runId).toBe(RUN_ID);
    expect(result.current.isRunning).toBe(false);
  });

  it("surfaces an error event", async () => {
    mockFetchSSE([{ event: "error", error: "chrome died" }]);
    const { result } = renderHookWithQuery(() => useBrowserAgent());
    act(() => result.current.run("q"));

    await waitFor(() => expect(result.current.error).toBe("chrome died"));
    expect(result.current.isRunning).toBe(false);
  });

  it("treats a 503 as the disabled state, not an error", async () => {
    mockFetchStatus(503, {
      detail: "The browser agent is disabled.",
      hint: "Enable it in LLM Settings.",
    });
    const { result } = renderHookWithQuery(() => useBrowserAgent());
    act(() => result.current.run("q"));

    await waitFor(() => expect(result.current.disabled).not.toBeNull());
    expect(result.current.disabled?.hint).toBe("Enable it in LLM Settings.");
    expect(result.current.error).toBeNull();
  });

  it("reports a busy slot as an error", async () => {
    mockFetchStatus(429, { detail: "A browser run is already in progress." });
    const { result } = renderHookWithQuery(() => useBrowserAgent());
    act(() => result.current.run("q"));

    await waitFor(() =>
      expect(result.current.error).toBe("A browser run is already in progress."),
    );
  });

  it("hydrates from a stored run id on mount", async () => {
    localStorage.setItem(
      "browseSession",
      JSON.stringify({ query: "old query", runId: RUN_ID }),
    );
    server.use(
      http.get(`${BASE}/api/llm/browser/${RUN_ID}/`, () =>
        HttpResponse.json({
          id: RUN_ID,
          query: "old query",
          provider: "anthropic",
          model: "",
          max_steps: 15,
          allowed_domains: [],
          urls_visited: ["https://example.com"],
          stop_reason: "complete",
          duration_s: 12,
          status: "done",
          output: "restored answer",
          error: "",
          created_at: "2026-08-05T10:00:00Z",
          completed_at: "2026-08-05T10:01:00Z",
          steps: [],
        }),
      ),
    );

    const { result } = renderHookWithQuery(() => useBrowserAgent());
    await waitFor(() => expect(result.current.output).toBe("restored answer"));
    expect(result.current.query).toBe("old query");
    expect(result.current.sources).toEqual(["https://example.com"]);
  });

  it("persists the workspace to its own storage key", async () => {
    mockFetchSSE([stepEvent(0), RESULT_EVENT]);
    const { result } = renderHookWithQuery(() => useBrowserAgent());
    act(() => result.current.run("persist me"));

    await waitFor(() => expect(result.current.runId).toBe(RUN_ID));
    const stored = JSON.parse(localStorage.getItem("browseSession") ?? "{}");
    expect(stored).toEqual({ query: "persist me", runId: RUN_ID });
    // The Agents page's session must be untouched.
    expect(localStorage.getItem("agentsSession")).toBeNull();
  });

  it("stop posts the cancel and clears the running flag", async () => {
    mockFetchSSE([stepEvent(0), RESULT_EVENT]);
    let stopped = false;
    server.use(
      http.post(`${BASE}/api/llm/runs/stop/`, async ({ request }) => {
        const body = (await request.json()) as { type: string; id: string };
        stopped = body.type === "browser" && body.id === RUN_ID;
        return HttpResponse.json({ stopped: true });
      }),
    );

    const { result } = renderHookWithQuery(() => useBrowserAgent());
    act(() => result.current.run("q"));
    await waitFor(() => expect(result.current.runId).toBe(RUN_ID));

    act(() => result.current.stop());
    await waitFor(() => expect(stopped).toBe(true));
  });

  it("reset clears the workspace", async () => {
    mockFetchSSE([stepEvent(0), RESULT_EVENT]);
    const { result } = renderHookWithQuery(() => useBrowserAgent());
    act(() => result.current.run("q"));
    await waitFor(() => expect(result.current.output).toBeTruthy());

    act(() => result.current.reset());
    expect(result.current.steps).toEqual([]);
    expect(result.current.output).toBeNull();
    expect(result.current.runId).toBeNull();
  });
});

describe("useBrowserAgent - a failed request must not look like an empty run", () => {
  it("surfaces a server error rather than finishing blank", async () => {
    // Same defect as the chat one (issue #8): `readSSE` yields nothing for a JSON error
    // body, so without a throw the run ends looking finished with no answer and no reason.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => ({ detail: "Chromium failed to launch." }),
      }),
    );
    const { result } = renderHookWithQuery(() => useBrowserAgent());

    act(() => result.current.run("who won?"));

    await waitFor(() => expect(result.current.error).toBe("Chromium failed to launch."));
    expect(result.current.isRunning).toBe(false);
  });
});
