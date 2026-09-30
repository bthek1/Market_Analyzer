import React from "react";
import { describe, it, expect } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithQuery } from "@/test/render";
import { AiSummaryTab } from "@/components/companies/AiSummaryTab";
import type { CompanySummary } from "@/types/companies";

const BASE = "http://localhost:8004";

const makeSummary = (override: Partial<CompanySummary> = {}): CompanySummary => ({
  id: 1,
  generated_at: "2025-06-01T06:00:00Z",
  model_name: "llama3.2:3b",
  verdict: "buy",
  summary: "Strong fundamentals and solid revenue growth.\n\nVERDICT: BUY",
  ...override,
});

function mockList(items: CompanySummary[]) {
  server.use(
    http.get(`${BASE}/api/companies/:symbol/summaries/`, () =>
      HttpResponse.json({ count: items.length, next: null, previous: null, results: items }),
    ),
  );
}

function mockEmptyList() {
  server.use(
    http.get(`${BASE}/api/companies/:symbol/summaries/`, () =>
      HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
    ),
  );
}

describe("AiSummaryTab", () => {
  describe("loading state", () => {
    it("renders skeleton while loading", () => {
      server.use(
        http.get(`${BASE}/api/companies/:symbol/summaries/`, async () => {
          await new Promise(() => {});
          return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
        }),
      );
      const { container } = renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      expect(container.querySelector(".animate-pulse")).toBeTruthy();
    });
  });

  describe("empty state", () => {
    it("shows empty message when no summaries exist", async () => {
      mockEmptyList();
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      await waitFor(() =>
        expect(screen.getByText(/No AI summary generated yet/)).toBeTruthy(),
      );
    });

    it("still renders the toolbar with Generate button when empty", async () => {
      mockEmptyList();
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      await waitFor(() =>
        expect(screen.getByRole("button", { name: /Generate New Summary/ })).toBeTruthy(),
      );
    });
  });

  describe("list rendering", () => {
    it("renders a list entry for each summary", async () => {
      mockList([
        makeSummary({ id: 1, generated_at: "2025-06-01T06:00:00Z", verdict: "buy" }),
        makeSummary({ id: 2, generated_at: "2025-05-01T06:00:00Z", verdict: "hold" }),
      ]);
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      await waitFor(() => {
        expect(screen.getAllByText("BUY").length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText("HOLD")).toBeTruthy();
      });
    });

    it("selects the first (latest) summary by default", async () => {
      const first = makeSummary({ id: 1, summary: "First summary text." });
      const second = makeSummary({ id: 2, summary: "Second summary text." });
      mockList([first, second]);
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      await waitFor(() =>
        expect(screen.getByText(/First summary text/)).toBeTruthy(),
      );
    });

    it("shows summary detail in the right panel for the selected item", async () => {
      mockList([
        makeSummary({ id: 1, summary: "Summary one content.", verdict: "buy" }),
        makeSummary({ id: 2, summary: "Summary two content.", verdict: "hold" }),
      ]);
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);

      // Click the second list item (HOLD)
      const holdBtn = await screen.findByText("HOLD");
      fireEvent.click(holdBtn.closest("button")!);

      await waitFor(() =>
        expect(screen.getByText(/Summary two content/)).toBeTruthy(),
      );
    });

    it("shows model name in the detail panel", async () => {
      mockList([makeSummary({ model_name: "llama3.2:3b" })]);
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      await waitFor(() =>
        expect(screen.getAllByText(/llama3\.2:3b/).length).toBeGreaterThanOrEqual(1),
      );
    });

    it("shows formatted date in the detail panel", async () => {
      mockList([makeSummary({ generated_at: "2025-06-01T06:00:00Z" })]);
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      await waitFor(() => {
        const text = document.body.textContent ?? "";
        expect(text).toMatch(/6\/1\/2025|01\/06\/2025|Jun.*2025/);
      });
    });
  });

  describe("verdict badges", () => {
    it("renders BUY badge with green styling", async () => {
      mockList([makeSummary({ verdict: "buy" })]);
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      await waitFor(() => {
        const badges = screen.getAllByText("BUY");
        expect(badges.some((b) => b.className.includes("green"))).toBe(true);
      });
    });

    it("renders HOLD badge with amber styling", async () => {
      mockList([makeSummary({ verdict: "hold" })]);
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      await waitFor(() => {
        const badge = screen.getAllByText("HOLD")[0];
        expect(badge.className).toContain("amber");
      });
    });

    it("renders SELL badge with red styling", async () => {
      mockList([makeSummary({ verdict: "sell" })]);
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      await waitFor(() => {
        const badge = screen.getAllByText("SELL")[0];
        expect(badge.className).toContain("red");
      });
    });

    it("renders INSUFFICIENT DATA badge with gray styling", async () => {
      mockList([makeSummary({ verdict: "insufficient_data" })]);
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      await waitFor(() => {
        const badge = screen.getAllByText("INSUFFICIENT DATA")[0];
        expect(badge.className).toContain("gray");
      });
    });
  });

  describe("Generate button", () => {
    it("is enabled when not generating", async () => {
      mockList([makeSummary()]);
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      await waitFor(() => {
        const btn = screen.getByRole("button", { name: /Generate New Summary/ });
        expect((btn as HTMLButtonElement).disabled).toBe(false);
      });
    });

    it("calls generate endpoint on button click", async () => {
      mockList([makeSummary()]);
      const captured: string[] = [];
      server.use(
        http.post(`${BASE}/api/companies/:symbol/summaries/generate/`, ({ params }) => {
          captured.push(params.symbol as string);
          return HttpResponse.json({ task_id: "t1", status: "queued" }, { status: 202 });
        }),
      );

      renderWithQuery(<AiSummaryTab symbol="TSLA" />);
      const btn = await screen.findByRole("button", { name: /Generate New Summary/ });
      fireEvent.click(btn);

      await waitFor(() => expect(captured).toContain("TSLA"));
    });

    it("shows Generating text and disables button while in flight", async () => {
      mockList([makeSummary()]);
      server.use(
        http.post(`${BASE}/api/companies/:symbol/summaries/generate/`, async () => {
          await new Promise(() => {});
          return HttpResponse.json({ task_id: "t2", status: "queued" }, { status: 202 });
        }),
      );

      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      const btn = await screen.findByRole("button", { name: /Generate New Summary/ });
      fireEvent.click(btn);

      await waitFor(() => {
        const generating = screen.getByRole("button", { name: /Generating/ });
        expect((generating as HTMLButtonElement).disabled).toBe(true);
      });
    });
  });

  describe("confidence, drivers and risks", () => {
    it("renders the confidence beside the verdict chip", async () => {
      mockList([makeSummary({ confidence: 0.72 })]);
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      await waitFor(() =>
        expect(screen.getByTestId("summary-confidence").textContent).toContain("72%"),
      );
    });

    it("omits confidence when the row has none", async () => {
      mockList([makeSummary({ confidence: null })]);
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      await waitFor(() => expect(screen.getByText(/Strong fundamentals/)).toBeTruthy());
      expect(screen.queryByTestId("summary-confidence")).toBeNull();
    });

    it("renders key drivers and key risks", async () => {
      mockList([
        makeSummary({
          key_drivers: ["operating margin 24.3% vs peer median 18.0%"],
          key_risks: ["trailing P/E 30.0 vs peer median 20.0"],
        }),
      ]);
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      await waitFor(() => {
        expect(screen.getByText("Key drivers")).toBeTruthy();
        expect(screen.getByText(/operating margin 24\.3%/)).toBeTruthy();
        expect(screen.getByText("Key risks")).toBeTruthy();
        expect(screen.getByText(/trailing P\/E 30\.0/)).toBeTruthy();
      });
    });

    it("omits empty driver and risk lists", async () => {
      mockList([makeSummary({ key_drivers: [], key_risks: [] })]);
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      await waitFor(() => expect(screen.getByText(/Strong fundamentals/)).toBeTruthy());
      expect(screen.queryByText("Key drivers")).toBeNull();
      expect(screen.queryByText("Key risks")).toBeNull();
    });
  });

  describe("stale data state", () => {
    it("renders the stale reason instead of a bare chip", async () => {
      mockList([
        makeSummary({
          verdict: "insufficient_data",
          summary: "Not enough up-to-date data to form a view.",
          data_snapshot: {
            symbol: "AAPL",
            stale_data: ["snapshot last synced 34 days ago (limit 7 days)"],
          },
        }),
      ]);
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      await waitFor(() =>
        expect(screen.getByTestId("summary-stale").textContent).toContain(
          "snapshot last synced 34 days ago",
        ),
      );
    });

    it("does not render the stale panel for a normal summary", async () => {
      mockList([makeSummary({ data_snapshot: { symbol: "AAPL" } })]);
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      await waitFor(() => expect(screen.getByText(/Strong fundamentals/)).toBeTruthy());
      expect(screen.queryByTestId("summary-stale")).toBeNull();
    });
  });

  describe("data used panel", () => {
    it("renders the collapsible panel including the peer benchmark", async () => {
      mockList([
        makeSummary({
          data_snapshot: {
            symbol: "AAPL",
            peers: { group: "industry", name: "Consumer Electronics", peers: 12 },
          },
        }),
      ]);
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      const toggle = await screen.findByText("Data used");
      fireEvent.click(toggle);
      await waitFor(() => {
        expect(document.body.textContent).toContain("Consumer Electronics");
      });
    });

    it("omits the panel when the row carries no data_snapshot", async () => {
      mockList([makeSummary({ data_snapshot: undefined })]);
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      await waitFor(() => expect(screen.getByText(/Strong fundamentals/)).toBeTruthy());
      expect(screen.queryByText("Data used")).toBeNull();
    });
  });

  describe("backwards compatibility", () => {
    it("renders a pre-Phase-2 summary with none of the new fields", async () => {
      const legacy = {
        id: 9,
        generated_at: "2025-06-01T06:00:00Z",
        model_name: "llama3.2:3b",
        verdict: "hold",
        summary: "Legacy prose with a trailing line.\n\nVERDICT: HOLD",
      } as CompanySummary;
      mockList([legacy]);
      renderWithQuery(<AiSummaryTab symbol="AAPL" />);
      await waitFor(() => expect(screen.getByText(/Legacy prose/)).toBeTruthy());
      expect(screen.queryByTestId("summary-confidence")).toBeNull();
      expect(screen.queryByText("Data used")).toBeNull();
    });
  });
});
