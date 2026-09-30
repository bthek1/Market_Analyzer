import { describe, it, expect } from "vitest";
import { waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderHookWithQuery } from "@/test/render";
import { useLLMSettings, useUpdateLLMSettings } from "@/hooks/useLLMSettings";
import type { LLMSettings } from "@/types/llm";

const BASE = "http://localhost:8004";

const MOCK_SETTINGS: LLMSettings = {
  base_url: "http://localhost:11434",
  main_model: "qwen3:8b",
  classifier_model: "qwen3:1.7b",
  embed_model: "nomic-embed-text",
  timeout: 60,
  num_parallel: 4,
  route_mode: "llm",
  route_threshold: 0.75,
  react_max_steps: 6,
  eval_max_iterations: 3,
  eval_threshold: 8,
  plan_max_steps: 20,
  plan_max_replans: 5,
  updated_at: "2026-06-11T00:00:00Z",
};

describe("useLLMSettings", () => {
  it("fetches the current config", async () => {
    server.use(
      http.get(`${BASE}/api/llm/settings/`, () => HttpResponse.json(MOCK_SETTINGS)),
    );
    const { result } = renderHookWithQuery(() => useLLMSettings());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.main_model).toBe("qwen3:8b");
    expect(result.current.data?.route_mode).toBe("llm");
  });

  it("sends a PUT and caches the updated config", async () => {
    let received: Partial<LLMSettings> | null = null;
    server.use(
      http.put(`${BASE}/api/llm/settings/`, async ({ request }) => {
        received = (await request.json()) as Partial<LLMSettings>;
        return HttpResponse.json({ ...MOCK_SETTINGS, ...received });
      }),
    );
    const { result } = renderHookWithQuery(() => useUpdateLLMSettings());
    result.current.mutate({ ...MOCK_SETTINGS, main_model: "llama3:8b", route_mode: "semantic" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(received).not.toBeNull();
    expect(received!.main_model).toBe("llama3:8b");
    expect(result.current.data?.route_mode).toBe("semantic");
  });
});
