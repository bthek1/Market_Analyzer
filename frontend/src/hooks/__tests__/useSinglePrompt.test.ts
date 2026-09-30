import { describe, it, expect, afterEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { useSinglePrompt } from "@/hooks/useSinglePrompt";

const BASE = "http://localhost:8004";

afterEach(() => {
  server.resetHandlers();
});

describe("useSinglePrompt — initial state", () => {
  it("starts with null result, not running, no elapsed time, no error", () => {
    const { result } = renderHook(() => useSinglePrompt());
    expect(result.current.result).toBeNull();
    expect(result.current.isRunning).toBe(false);
    expect(result.current.elapsedMs).toBeNull();
    expect(result.current.error).toBeNull();
  });
});

describe("useSinglePrompt — successful run", () => {
  it("sets result to the API response content", async () => {
    const { result } = renderHook(() => useSinglePrompt());

    await act(async () => {
      result.current.run("What is AAPL?");
    });

    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(result.current.result).toBe("Hello from Ollama!");
    expect(result.current.error).toBeNull();
  });

  it("isRunning is false after the request completes", async () => {
    const { result } = renderHook(() => useSinglePrompt());

    await act(async () => {
      result.current.run("test query");
    });

    await waitFor(() => expect(result.current.isRunning).toBe(false));
  });

  it("elapsedMs is a non-negative number after completion", async () => {
    const { result } = renderHook(() => useSinglePrompt());

    await act(async () => {
      result.current.run("test query");
    });

    await waitFor(() => expect(result.current.elapsedMs).not.toBeNull());
    expect(result.current.elapsedMs).toBeGreaterThanOrEqual(0);
  });

  it("forwards query as user message in request body", async () => {
    let capturedBody: unknown = null;

    server.use(
      http.post(`${BASE}/api/llm/chat/`, async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({ content: "ok" });
      }),
    );

    const { result } = renderHook(() => useSinglePrompt());

    await act(async () => {
      result.current.run("Analyse MSFT");
    });

    await waitFor(() => expect(result.current.isRunning).toBe(false));

    expect(capturedBody).toMatchObject({
      messages: [{ role: "user", content: "Analyse MSFT" }],
    });
  });

  it("forwards model name when provided", async () => {
    let capturedBody: unknown = null;

    server.use(
      http.post(`${BASE}/api/llm/chat/`, async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({ content: "ok" });
      }),
    );

    const { result } = renderHook(() => useSinglePrompt());

    await act(async () => {
      result.current.run("test", "mistral:latest");
    });

    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(capturedBody).toMatchObject({ model: "mistral:latest" });
  });

  it("sends null model when not provided", async () => {
    let capturedBody: unknown = null;

    server.use(
      http.post(`${BASE}/api/llm/chat/`, async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({ content: "ok" });
      }),
    );

    const { result } = renderHook(() => useSinglePrompt());

    await act(async () => {
      result.current.run("test");
    });

    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(capturedBody).toMatchObject({ model: null });
  });
});

describe("useSinglePrompt — error handling", () => {
  it("sets error when API returns 500", async () => {
    server.use(
      http.post(`${BASE}/api/llm/chat/`, () =>
        HttpResponse.json({ detail: "Internal error" }, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useSinglePrompt());

    await act(async () => {
      result.current.run("test");
    });

    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(result.current.error).not.toBeNull();
    expect(result.current.result).toBeNull();
  });

  it("records elapsedMs even on failure", async () => {
    server.use(
      http.post(`${BASE}/api/llm/chat/`, () =>
        HttpResponse.json({}, { status: 503 }),
      ),
    );

    const { result } = renderHook(() => useSinglePrompt());

    await act(async () => {
      result.current.run("test");
    });

    await waitFor(() => expect(result.current.isRunning).toBe(false));
    expect(result.current.elapsedMs).not.toBeNull();
  });

  it("clears previous error on next successful run", async () => {
    server.use(
      http.post(`${BASE}/api/llm/chat/`, () =>
        HttpResponse.json({}, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useSinglePrompt());

    await act(async () => {
      result.current.run("first");
    });
    await waitFor(() => expect(result.current.error).not.toBeNull());

    // restore default handler
    server.resetHandlers();

    await act(async () => {
      result.current.run("second");
    });
    await waitFor(() => expect(result.current.isRunning).toBe(false));

    expect(result.current.error).toBeNull();
    expect(result.current.result).toBe("Hello from Ollama!");
  });
});

describe("useSinglePrompt — reset", () => {
  it("reset clears result, error, and elapsedMs", async () => {
    const { result } = renderHook(() => useSinglePrompt());

    await act(async () => {
      result.current.run("test");
    });
    await waitFor(() => expect(result.current.result).not.toBeNull());

    act(() => {
      result.current.reset();
    });

    expect(result.current.result).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.elapsedMs).toBeNull();
    expect(result.current.isRunning).toBe(false);
  });
});
