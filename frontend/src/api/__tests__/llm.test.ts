import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { fetchModels, postAnalyse, postChat, postSummarise } from "@/api/llm";
import { MOCK_LLM_MODELS } from "@/test/handlers";

const BASE = "http://localhost:8004";

describe("fetchModels", () => {
  it("returns model list from /api/llm/models/", async () => {
    const result = await fetchModels();
    expect(result).toHaveLength(2);
    expect(result[0].name).toBe("llama3.2:latest");
    expect(result[0].size_gb).toBe(2.0);
  });

  it("throws on 503", async () => {
    server.use(
      http.get(`${BASE}/api/llm/models/`, () =>
        HttpResponse.json({ detail: "Ollama unavailable" }, { status: 503 }),
      ),
    );
    await expect(fetchModels()).rejects.toThrow();
  });

  it("returns empty array when no models available", async () => {
    server.use(
      http.get(`${BASE}/api/llm/models/`, () => HttpResponse.json([])),
    );
    const result = await fetchModels();
    expect(result).toEqual([]);
  });

  it("returns all fields including size_gb", async () => {
    const result = await fetchModels();
    expect(result[1]).toEqual(MOCK_LLM_MODELS[1]);
  });
});

describe("postChat", () => {
  it("posts messages and returns content", async () => {
    const result = await postChat({
      messages: [{ role: "user", content: "Hi" }],
    });
    expect(result.content).toBe("Hello from Ollama!");
  });

  it("sends model override in body", async () => {
    let capturedBody: unknown;
    server.use(
      http.post(`${BASE}/api/llm/chat/`, async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({ content: "ok" });
      }),
    );
    await postChat({ messages: [{ role: "user", content: "Hi" }], model: "mistral" });
    expect((capturedBody as Record<string, unknown>).model).toBe("mistral");
  });

  it("sends full message history", async () => {
    let capturedBody: unknown;
    server.use(
      http.post(`${BASE}/api/llm/chat/`, async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({ content: "ok" });
      }),
    );
    const messages = [
      { role: "user" as const, content: "Hello" },
      { role: "assistant" as const, content: "Hi there" },
      { role: "user" as const, content: "How are you?" },
    ];
    await postChat({ messages });
    expect((capturedBody as Record<string, unknown>).messages).toHaveLength(3);
  });

  it("throws on 503", async () => {
    server.use(
      http.post(`${BASE}/api/llm/chat/`, () =>
        HttpResponse.json({ detail: "Ollama unavailable" }, { status: 503 }),
      ),
    );
    await expect(postChat({ messages: [{ role: "user", content: "hi" }] })).rejects.toThrow();
  });
});

describe("postSummarise", () => {
  it("posts text and returns summary", async () => {
    const result = await postSummarise({ text: "Long article..." });
    expect(result.content).toBe("Short summary.");
  });

  it("sends model override when provided", async () => {
    let capturedBody: unknown;
    server.use(
      http.post(`${BASE}/api/llm/summarise/`, async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({ content: "summary" });
      }),
    );
    await postSummarise({ text: "text", model: "llama3.2:latest" });
    expect((capturedBody as Record<string, unknown>).model).toBe("llama3.2:latest");
  });

  it("throws on 503", async () => {
    server.use(
      http.post(`${BASE}/api/llm/summarise/`, () =>
        HttpResponse.json({ detail: "err" }, { status: 503 }),
      ),
    );
    await expect(postSummarise({ text: "text" })).rejects.toThrow();
  });
});

describe("postAnalyse", () => {
  it("posts text and returns analysis", async () => {
    const result = await postAnalyse({ text: "Financial data..." });
    expect(result.content).toBe("Detailed analysis.");
  });

  it("sends context field when provided", async () => {
    let capturedBody: unknown;
    server.use(
      http.post(`${BASE}/api/llm/analyse/`, async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({ content: "analysis" });
      }),
    );
    await postAnalyse({ text: "data", context: "background info" });
    expect((capturedBody as Record<string, unknown>).context).toBe("background info");
  });

  it("throws on 503", async () => {
    server.use(
      http.post(`${BASE}/api/llm/analyse/`, () =>
        HttpResponse.json({ detail: "err" }, { status: 503 }),
      ),
    );
    await expect(postAnalyse({ text: "text" })).rejects.toThrow();
  });
});
