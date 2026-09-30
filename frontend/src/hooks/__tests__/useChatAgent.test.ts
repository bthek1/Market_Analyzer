/**
 * The chat agent hook (issue #8 phase 4).
 *
 * The parity case lives here rather than in `sseMatchesDetail.test.ts` because chat's unit
 * of restore is a SESSION, not a run: the detail payload is a conversation containing turns
 * containing steps, so the shared harness's "select the step list" shape does not fit. The
 * invariant under test is the same one, and so is the discipline - the fixtures are written
 * once and used on both paths, so a case fails if either side is changed alone.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, waitFor } from "@testing-library/react";
import { renderHookWithQuery } from "@/test/render";
import { useChatAgent } from "@/hooks/useChatAgent";
import type { ChatSessionDetail } from "@/types/chat";

const SESSION_ID = "11111111-1111-1111-1111-111111111111";
const RUN_ID = "22222222-2222-2222-2222-222222222222";
const ARGS = { symbol: "AAPL" };
const OBS = '{"trailing_pe": 39.07}';

/** The persisted step rows, shared by the stream and the detail payload. */
const TOOL_STEP = {
  id: "step-0",
  order: 0,
  thought: "I need AAPL's snapshot",
  tool: "company_snapshot",
  tool_args: ARGS,
  observation: OBS,
  is_answer: false,
  status: "done" as const,
  error: "",
  created_at: "2026-09-28T00:00:00Z",
};

const ANSWER_STEP = {
  id: "step-1",
  order: 1,
  thought: "I have it",
  tool: "",
  tool_args: null,
  observation: "",
  is_answer: true,
  status: "done" as const,
  error: "",
  created_at: "2026-09-28T00:00:01Z",
};

const STARTED = {
  event: "started",
  run_id: RUN_ID,
  session_id: SESSION_ID,
  max_steps: 4,
  tools: ["company_snapshot"],
  history: 0,
  compacted: 0,
};

const RESULT = {
  event: "result",
  output: "AAPL's trailing P/E is 39.07.",
  run_id: RUN_ID,
};

function detailFor(status: "done" | "running" = "done"): ChatSessionDetail {
  return {
    id: SESSION_ID,
    title: "AAPL valuation",
    archived: false,
    turn_count: 1,
    last_message_at: "2026-09-28T00:00:02Z",
    created_at: "2026-09-28T00:00:00Z",
    updated_at: "2026-09-28T00:00:02Z",
    summary: "",
    summarised_upto: 0,
    turns: [
      {
        id: RUN_ID,
        query: "What is AAPL's trailing P/E?",
        model: "",
        max_steps: 4,
        turn: 0,
        tools_used: ["company_snapshot"],
        compacted: 0,
        status,
        output: status === "done" ? RESULT.output : "",
        error: "",
        created_at: "2026-09-28T00:00:00Z",
        completed_at: status === "done" ? "2026-09-28T00:00:02Z" : null,
        steps: [TOOL_STEP, ANSWER_STEP],
      },
    ],
  };
}

function mockSSE(events: object[]) {
  const encoder = new TextEncoder();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: new ReadableStream<Uint8Array>({
        start(controller) {
          for (const evt of events) {
            controller.enqueue(encoder.encode(`data: ${JSON.stringify(evt)}\n\n`));
          }
          controller.close();
        },
      }),
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("useChatAgent - live stream state === refresh-restore state", () => {
  it("a streamed turn and a restored one produce equal transcript state", async () => {
    mockSSE([
      STARTED,
      { event: "step", ...TOOL_STEP },
      { event: "step", ...ANSWER_STEP },
      RESULT,
    ]);

    const streamed = renderHookWithQuery(() => useChatAgent());
    act(() => streamed.result.current.send("What is AAPL's trailing P/E?"));
    await waitFor(() => expect(streamed.result.current.isRunning).toBe(false));

    const restored = renderHookWithQuery(() => useChatAgent());
    act(() => restored.result.current.loadFromDetail(detailFor()));

    // Length first: a step persisted but never streamed makes the live transcript shorter
    // than the restored one while every card in it matches (issue #7's class).
    expect(streamed.result.current.turns).toHaveLength(1);
    expect(streamed.result.current.turns[0].steps).toHaveLength(2);
    expect(streamed.result.current.turns).toEqual(restored.result.current.turns);
  });

  it("keeps tool_args on both paths", async () => {
    // The field seven of ten workflows disagreed about before issue #6. Named explicitly so
    // a regression reports the field rather than a whole-object diff.
    mockSSE([STARTED, { event: "step", ...TOOL_STEP }, RESULT]);

    const streamed = renderHookWithQuery(() => useChatAgent());
    act(() => streamed.result.current.send("q"));
    await waitFor(() => expect(streamed.result.current.isRunning).toBe(false));

    const restored = renderHookWithQuery(() => useChatAgent());
    act(() => restored.result.current.loadFromDetail(detailFor()));

    expect(streamed.result.current.turns[0].steps[0].tool_args).toEqual(ARGS);
    expect(restored.result.current.turns[0].steps[0].tool_args).toEqual(ARGS);
  });
});

describe("useChatAgent - sending", () => {
  it("renders the user's message before the reply arrives", async () => {
    mockSSE([STARTED, RESULT]);
    const { result } = renderHookWithQuery(() => useChatAgent());

    act(() => result.current.send("hello"));

    expect(result.current.turns[0].query).toBe("hello");
    await waitFor(() => expect(result.current.turns[0].output).toBe(RESULT.output));
  });

  it("adopts the session the server created", async () => {
    mockSSE([STARTED, RESULT]);
    const { result } = renderHookWithQuery(() => useChatAgent());

    act(() => result.current.send("hello"));
    await waitFor(() => expect(result.current.sessionId).toBe(SESSION_ID));
  });

  it("ignores an empty message and a second send while one is running", async () => {
    mockSSE([STARTED, RESULT]);
    const { result } = renderHookWithQuery(() => useChatAgent());

    act(() => result.current.send("   "));
    expect(result.current.turns).toHaveLength(0);

    act(() => result.current.send("first"));
    act(() => result.current.send("second"));
    expect(result.current.turns).toHaveLength(1);
  });

  it("drops the optimistic turn when the server refuses with 409", async () => {
    // Otherwise the transcript shows a message that was never sent and never answered.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 409,
        json: async () => ({ detail: "This conversation already has a turn in progress." }),
      }),
    );
    const { result } = renderHookWithQuery(() => useChatAgent());

    act(() => result.current.send("me too"));

    await waitFor(() => expect(result.current.error).toMatch(/already has a turn/));
    expect(result.current.turns).toHaveLength(0);
    expect(result.current.isRunning).toBe(false);
  });

  it("marks the turn errored when the stream reports one", async () => {
    mockSSE([STARTED, { event: "error", error: "Ollama is down" }]);
    const { result } = renderHookWithQuery(() => useChatAgent());

    act(() => result.current.send("hi"));

    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(result.current.turns[0].status).toBe("error");
    expect(result.current.turns[0].error).toBe("Ollama is down");
  });

  it("marks the turn stopped and keeps it in the transcript", async () => {
    // A stopped turn is part of what the user saw, and the backend replays its partial
    // output into the next turn's prompt - so the UI must not hide it.
    mockSSE([STARTED, { event: "stopped" }]);
    const { result } = renderHookWithQuery(() => useChatAgent());

    act(() => result.current.send("hi"));

    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(result.current.turns).toHaveLength(1);
    expect(result.current.turns[0].status).toBe("stopped");
  });
});

describe("useChatAgent - sessions", () => {
  it("persists only the session id, never the transcript", async () => {
    // The server owns the transcript (query/output ARE the messages). A local copy would be
    // a second source of truth that drifts from what the model is actually sent.
    mockSSE([STARTED, RESULT]);
    const { result } = renderHookWithQuery(() => useChatAgent());

    act(() => result.current.send("hello"));
    await waitFor(() => expect(result.current.sessionId).toBe(SESSION_ID));

    expect(localStorage.getItem("chatSession")).toBe(SESSION_ID);
    expect(JSON.stringify(localStorage)).not.toContain("hello");
  });

  it("newSession clears the transcript without creating an empty row", async () => {
    mockSSE([STARTED, RESULT]);
    const { result } = renderHookWithQuery(() => useChatAgent());
    act(() => result.current.send("hello"));
    await waitFor(() => expect(result.current.turns).toHaveLength(1));

    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.length;
    act(() => result.current.newSession());

    expect(result.current.turns).toHaveLength(0);
    expect(result.current.sessionId).toBeNull();
    expect(localStorage.getItem("chatSession")).toBeNull();
    // No POST: the turn endpoint creates the session, so an abandoned "New chat" leaves
    // nothing behind.
    expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(calls);
  });

  it("loadFromDetail marks a still-running turn as running", () => {
    // A refresh mid-turn must reconnect, not show a finished-looking blank reply.
    const { result } = renderHookWithQuery(() => useChatAgent());

    act(() => result.current.loadFromDetail(detailFor("running")));

    expect(result.current.isRunning).toBe(true);
    expect(result.current.turns[0].status).toBe("running");
  });

  it("loadFromDetail exposes the compaction summary", () => {
    const detail = { ...detailFor(), summary: "They asked about AAPL.", summarised_upto: 4 };
    const { result } = renderHookWithQuery(() => useChatAgent());

    act(() => result.current.loadFromDetail(detail));

    expect(result.current.summary).toBe("They asked about AAPL.");
  });
});

describe("useChatAgent - switching conversations", () => {
  it("openSession replaces the transcript and drops the live stream", async () => {
    // Bleed between conversations is the failure this prevents: turns from the old session
    // left on screen under the new session's id, which the next message would follow on
    // from as if they had been said.
    mockSSE([STARTED, RESULT]);
    const { result } = renderHookWithQuery(() => useChatAgent());
    act(() => result.current.send("first conversation"));
    await waitFor(() => expect(result.current.turns).toHaveLength(1));

    const other = {
      ...detailFor(),
      id: "33333333-3333-3333-3333-333333333333",
      title: "Other chat",
      turns: [{ ...detailFor().turns[0], id: "other-run", query: "different question" }],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => other,
      headers: new Headers({ "content-type": "application/json" }),
    }));

    act(() => result.current.openSession(other.id));

    // Cleared synchronously - the old transcript must not linger while the fetch is in
    // flight under the NEW session id.
    expect(result.current.turns).toHaveLength(0);
    expect(result.current.sessionId).toBe(other.id);
    expect(result.current.isRunning).toBe(false);
  });
});

describe("useChatAgent - token streaming", () => {
  const DELTAS = ["AAPL trades ", "at 39.07x ", "trailing earnings."];
  const ANSWER = DELTAS.join("");

  it("renders the reply as it is written", async () => {
    mockSSE([
      STARTED,
      ...DELTAS.map((text) => ({ event: "delta", text })),
      { event: "result", output: ANSWER, run_id: RUN_ID },
    ]);
    const { result } = renderHookWithQuery(() => useChatAgent());

    act(() => result.current.send("what is AAPL's PE?"));

    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(result.current.turns[0].output).toBe(ANSWER);
  });

  it("appends deltas rather than replacing, so nothing is lost mid-reply", async () => {
    // Replacing would show only the last token until `result` arrived - which looks like
    // streaming in a screenshot and like a flicker in use.
    mockSSE([STARTED, ...DELTAS.map((text) => ({ event: "delta", text }))]);
    const { result } = renderHookWithQuery(() => useChatAgent());

    act(() => result.current.send("q"));

    await waitFor(() => expect(result.current.turns[0].output).toBe(ANSWER));
  });

  it("the streamed text and the authoritative result agree", async () => {
    // The backend persists exactly what it streamed. If these two could differ, `result`
    // would visibly rewrite a reply the user had already read.
    mockSSE([
      STARTED,
      ...DELTAS.map((text) => ({ event: "delta", text })),
      { event: "result", output: ANSWER, run_id: RUN_ID },
    ]);
    const streamed = renderHookWithQuery(() => useChatAgent());
    act(() => streamed.result.current.send("q"));
    await waitFor(() => expect(streamed.result.current.isRunning).toBe(false));

    const restored = renderHookWithQuery(() => useChatAgent());
    act(() =>
      restored.result.current.loadFromDetail({
        ...detailFor(),
        turns: [{ ...detailFor().turns[0], output: ANSWER, steps: [] }],
      }),
    );

    expect(streamed.result.current.turns[0].output).toBe(
      restored.result.current.turns[0].output,
    );
  });

  it("keeps a partial reply when the turn is stopped mid-stream", async () => {
    // What the user saw is what the backend replays into the next prompt, so the UI must
    // not discard it.
    mockSSE([STARTED, { event: "delta", text: "I was halfway thr" }, { event: "stopped" }]);
    const { result } = renderHookWithQuery(() => useChatAgent());

    act(() => result.current.send("q"));

    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(result.current.turns[0].output).toBe("I was halfway thr");
    expect(result.current.turns[0].status).toBe("stopped");
  });
});

describe("useChatAgent - a failed turn must never look like a blank reply", () => {
  /**
   * Reported from the browser: two messages, both showing "No reply." and no error. Every
   * one of these paths produced that, because `readSSE` finds no `data:` lines in a JSON
   * error body, yields nothing, and returns normally - so the turn simply ended empty.
   */
  it("surfaces a server error instead of an empty bubble", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => ({ detail: "Ollama is unreachable." }),
      }),
    );
    const { result } = renderHookWithQuery(() => useChatAgent());

    act(() => result.current.send("whats the time?"));

    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(result.current.error).toBe("Ollama is unreachable.");
    expect(result.current.turns[0].status).toBe("error");
  });

  it("falls back to the status code when the body carries no detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 502, json: async () => ({}) }),
    );
    const { result } = renderHookWithQuery(() => useChatAgent());

    act(() => result.current.send("hi"));

    await waitFor(() => expect(result.current.error).toMatch(/HTTP 502/));
  });

  it("refreshes an expired access token and retries once", async () => {
    // The whole reason this bug existed: `fetch` bypasses the axios 401 interceptor, so chat
    // was the only surface that did NOT silently recover from an expired access token.
    localStorage.setItem("refresh_token", "r-1");
    const encoder = new TextEncoder();
    const ok = {
      ok: true,
      status: 200,
      body: new ReadableStream<Uint8Array>({
        start(controller) {
          for (const evt of [STARTED, { event: "result", output: "hi", run_id: RUN_ID }]) {
            controller.enqueue(encoder.encode(`data: ${JSON.stringify(evt)}\n\n`));
          }
          controller.close();
        },
      }),
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({}) })
      // the refresh call itself (axios uses XHR under jsdom, so stub the token directly)
      .mockResolvedValue(ok);
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(await import("@/api/client"), "refreshAccessToken").mockResolvedValue("new-token");

    const { result } = renderHookWithQuery(() => useChatAgent());
    act(() => result.current.send("hi"));

    await waitFor(() => expect(result.current.turns[0].output).toBe("hi"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const retryHeaders = fetchMock.mock.calls[1][1].headers as Record<string, string>;
    expect(retryHeaders.Authorization).toBe("Bearer new-token");
  });

  it("reports a stream that ends without finishing the turn", async () => {
    // A 200 whose generator dies before `result`. Previously indistinguishable from success.
    mockSSE([STARTED, { event: "step", ...TOOL_STEP }]);
    const { result } = renderHookWithQuery(() => useChatAgent());

    act(() => result.current.send("whats the time?"));

    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(result.current.error).toMatch(/connection ended/i);
    expect(result.current.turns[0].status).toBe("error");
  });

  it("does not report a clean stream as unfinished", async () => {
    mockSSE([STARTED, { event: "result", output: "fine", run_id: RUN_ID }]);
    const { result } = renderHookWithQuery(() => useChatAgent());

    act(() => result.current.send("hi"));

    await waitFor(() => expect(result.current.turns[0].output).toBe("fine"));
    expect(result.current.error).toBeNull();
  });
});
