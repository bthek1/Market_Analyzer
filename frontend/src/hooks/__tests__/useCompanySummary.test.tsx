import { describe, it, expect } from "vitest";
import { act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderHookWithQuery } from "@/test/render";
import { useCompanySummary, useCompanySummaryList } from "@/hooks/useCompanySummary";
import type { CompanySummary } from "@/types/companies";

const BASE = "http://localhost:8004";

const MOCK_SUMMARY: CompanySummary = {
  id: 1,
  generated_at: "2025-06-01T06:00:00Z",
  model_name: "llama3.2:3b",
  verdict: "buy",
  summary: "Strong fundamentals. Revenue growing at 8% YoY. Analyst consensus is buy.\n\nVERDICT: BUY",
};

describe("useCompanySummary", () => {
  describe("query", () => {
    it("returns summary on success", async () => {
      server.use(
        http.get(`${BASE}/api/companies/:symbol/summaries/latest/`, () =>
          HttpResponse.json(MOCK_SUMMARY),
        ),
      );
      const { result } = renderHookWithQuery(() => useCompanySummary("AAPL"));
      await waitFor(() => expect(result.current.isLoading).toBe(false));
      expect(result.current.summary).toEqual(MOCK_SUMMARY);
      expect(result.current.notFound).toBe(false);
      expect(result.current.isError).toBe(false);
    });

    it("sets notFound true on 404", async () => {
      server.use(
        http.get(`${BASE}/api/companies/:symbol/summaries/latest/`, () =>
          HttpResponse.json({ detail: "Not found." }, { status: 404 }),
        ),
      );
      const { result } = renderHookWithQuery(() => useCompanySummary("AAPL"));
      await waitFor(() => expect(result.current.isLoading).toBe(false));
      expect(result.current.notFound).toBe(true);
      expect(result.current.summary).toBeUndefined();
    });

    it("sets isError true on server error", async () => {
      server.use(
        http.get(`${BASE}/api/companies/:symbol/summaries/latest/`, () =>
          HttpResponse.json({ detail: "Server error." }, { status: 500 }),
        ),
      );
      const { result } = renderHookWithQuery(() => useCompanySummary("AAPL"));
      await waitFor(() => expect(result.current.isLoading).toBe(false));
      expect(result.current.isError).toBe(true);
      expect(result.current.notFound).toBe(false);
    });

    it("exposes verdict on successful response", async () => {
      server.use(
        http.get(`${BASE}/api/companies/:symbol/summaries/latest/`, () =>
          HttpResponse.json({ ...MOCK_SUMMARY, verdict: "hold" }),
        ),
      );
      const { result } = renderHookWithQuery(() => useCompanySummary("MSFT"));
      await waitFor(() => expect(result.current.isLoading).toBe(false));
      expect(result.current.summary?.verdict).toBe("hold");
    });

    it("starts in loading state", () => {
      server.use(
        http.get(`${BASE}/api/companies/:symbol/summaries/latest/`, () =>
          HttpResponse.json(MOCK_SUMMARY),
        ),
      );
      const { result } = renderHookWithQuery(() => useCompanySummary("AAPL"));
      expect(result.current.isLoading).toBe(true);
      expect(result.current.summary).toBeUndefined();
    });
  });

  describe("generate mutation", () => {
    it("exposes generate function and isGenerating flag", async () => {
      const { result } = renderHookWithQuery(() => useCompanySummary("AAPL"));
      await waitFor(() => expect(result.current.isLoading).toBe(false));
      expect(typeof result.current.generate).toBe("function");
      expect(result.current.isGenerating).toBe(false);
    });

    it("isGenerating is true while mutation is in flight", async () => {
      let resolvePost!: () => void;
      server.use(
        http.post(`${BASE}/api/companies/:symbol/summaries/generate/`, () =>
          new Promise<Response>((resolve) => {
            resolvePost = () =>
              resolve(
                HttpResponse.json({ task_id: "abc", status: "queued" }, { status: 202 }) as Response,
              );
          }),
        ),
      );

      const { result } = renderHookWithQuery(() => useCompanySummary("AAPL"));
      await waitFor(() => expect(result.current.isLoading).toBe(false));

      act(() => { result.current.generate(); });
      await waitFor(() => expect(result.current.isGenerating).toBe(true));

      act(() => { resolvePost(); });
      await waitFor(() => expect(result.current.isGenerating).toBe(false));
    });

    it("POST fires to the correct endpoint", async () => {
      const captured: string[] = [];
      server.use(
        http.post(`${BASE}/api/companies/:symbol/summaries/generate/`, ({ params }) => {
          captured.push(params.symbol as string);
          return HttpResponse.json({ task_id: "xyz", status: "queued" }, { status: 202 });
        }),
      );

      const { result } = renderHookWithQuery(() => useCompanySummary("TSLA"));
      await waitFor(() => expect(result.current.isLoading).toBe(false));

      await act(async () => { result.current.generate(); });
      await waitFor(() => expect(captured).toContain("TSLA"));
    });

    it("isGenerating returns to false after successful POST", async () => {
      server.use(
        http.post(`${BASE}/api/companies/:symbol/summaries/generate/`, () =>
          HttpResponse.json({ task_id: "done", status: "queued" }, { status: 202 }),
        ),
      );

      const { result } = renderHookWithQuery(() => useCompanySummary("AAPL"));
      await waitFor(() => expect(result.current.isLoading).toBe(false));

      await act(async () => { result.current.generate(); });
      await waitFor(() => expect(result.current.isGenerating).toBe(false));
    });
  });
});

describe("useCompanySummaryList", () => {
  it("returns summaries array on success", async () => {
    const items: CompanySummary[] = [
      { id: 1, generated_at: "2025-06-01T06:00:00Z", model_name: "llama3.2:3b", verdict: "buy", summary: "A" },
      { id: 2, generated_at: "2025-05-01T06:00:00Z", model_name: "llama3.2:3b", verdict: "hold", summary: "B" },
    ];
    server.use(
      http.get(`${BASE}/api/companies/:symbol/summaries/`, () =>
        HttpResponse.json({ count: 2, next: null, previous: null, results: items }),
      ),
    );
    const { result } = renderHookWithQuery(() => useCompanySummaryList("AAPL"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.summaries).toHaveLength(2);
    expect(result.current.summaries[0].verdict).toBe("buy");
  });

  it("returns empty array on empty response", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:symbol/summaries/`, () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
    );
    const { result } = renderHookWithQuery(() => useCompanySummaryList("AAPL"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.summaries).toEqual([]);
  });

  it("starts in loading state", () => {
    server.use(
      http.get(`${BASE}/api/companies/:symbol/summaries/`, async () => {
        await new Promise(() => {});
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );
    const { result } = renderHookWithQuery(() => useCompanySummaryList("AAPL"));
    expect(result.current.isLoading).toBe(true);
    expect(result.current.summaries).toEqual([]);
  });
});
