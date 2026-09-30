import React from "react";
import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithQuery } from "@/test/render";
import { SummaryCard } from "@/components/companies/SummaryCard";
import type { CompanySummary } from "@/types/companies";

const BASE = "http://localhost:8004";

const MOCK_SUMMARY: CompanySummary = {
  id: 1,
  generated_at: "2025-06-01T06:00:00Z",
  model_name: "llama3.2:3b",
  verdict: "buy",
  summary: "Strong fundamentals and solid revenue growth. Management is executing well.\n\nVERDICT: BUY",
};

function mockSummary(summary: Partial<CompanySummary> = {}) {
  server.use(
    http.get(`${BASE}/api/companies/:symbol/summaries/latest/`, () =>
      HttpResponse.json({ ...MOCK_SUMMARY, ...summary }),
    ),
  );
}

function mock404() {
  server.use(
    http.get(`${BASE}/api/companies/:symbol/summaries/latest/`, () =>
      HttpResponse.json({ detail: "Not found." }, { status: 404 }),
    ),
  );
}

describe("SummaryCard", () => {
  describe("loading state", () => {
    it("renders skeleton while loading", () => {
      server.use(
        http.get(`${BASE}/api/companies/:symbol/summaries/latest/`, async () => {
          await new Promise(() => {}); // never resolves
          return HttpResponse.json(MOCK_SUMMARY);
        }),
      );
      const { container } = renderWithQuery(<SummaryCard symbol="AAPL" />);
      expect(container.querySelector(".animate-pulse")).toBeTruthy();
    });
  });

  describe("no summary state", () => {
    it("shows empty state on 404", async () => {
      mock404();
      renderWithQuery(<SummaryCard symbol="AAPL" />);
      await waitFor(() =>
        expect(screen.getByText(/No AI summary available yet/)).toBeTruthy(),
      );
    });
  });

  describe("BUY verdict", () => {
    it("renders BUY badge", async () => {
      mockSummary({ verdict: "buy" });
      renderWithQuery(<SummaryCard symbol="AAPL" />);
      await waitFor(() => expect(screen.getByText("BUY")).toBeTruthy());
    });

    it("applies green styling to BUY badge", async () => {
      mockSummary({ verdict: "buy" });
      renderWithQuery(<SummaryCard symbol="AAPL" />);
      await waitFor(() => {
        const badge = screen.getByText("BUY");
        expect(badge.className).toContain("green");
      });
    });
  });

  describe("HOLD verdict", () => {
    it("renders HOLD badge", async () => {
      mockSummary({ verdict: "hold" });
      renderWithQuery(<SummaryCard symbol="MSFT" />);
      await waitFor(() => expect(screen.getByText("HOLD")).toBeTruthy());
    });

    it("applies amber styling to HOLD badge", async () => {
      mockSummary({ verdict: "hold" });
      renderWithQuery(<SummaryCard symbol="MSFT" />);
      await waitFor(() => {
        const badge = screen.getByText("HOLD");
        expect(badge.className).toContain("amber");
      });
    });
  });

  describe("SELL verdict", () => {
    it("renders SELL badge", async () => {
      mockSummary({ verdict: "sell" });
      renderWithQuery(<SummaryCard symbol="X" />);
      await waitFor(() => expect(screen.getByText("SELL")).toBeTruthy());
    });

    it("applies red styling to SELL badge", async () => {
      mockSummary({ verdict: "sell" });
      renderWithQuery(<SummaryCard symbol="X" />);
      await waitFor(() => {
        const badge = screen.getByText("SELL");
        expect(badge.className).toContain("red");
      });
    });
  });

  describe("INSUFFICIENT_DATA verdict", () => {
    it("renders INSUFFICIENT DATA badge", async () => {
      mockSummary({ verdict: "insufficient_data" });
      renderWithQuery(<SummaryCard symbol="STUB" />);
      await waitFor(() =>
        expect(screen.getByText("INSUFFICIENT DATA")).toBeTruthy(),
      );
    });

    it("applies grey styling to INSUFFICIENT_DATA badge", async () => {
      mockSummary({ verdict: "insufficient_data" });
      renderWithQuery(<SummaryCard symbol="STUB" />);
      await waitFor(() => {
        const badge = screen.getByText("INSUFFICIENT DATA");
        expect(badge.className).toContain("gray");
      });
    });
  });

  describe("summary content", () => {
    it("renders the summary text", async () => {
      mockSummary();
      renderWithQuery(<SummaryCard symbol="AAPL" />);
      await waitFor(() =>
        expect(screen.getByText(/Strong fundamentals/)).toBeTruthy(),
      );
    });

    it("renders model name", async () => {
      mockSummary({ model_name: "llama3.2:3b" });
      renderWithQuery(<SummaryCard symbol="AAPL" />);
      await waitFor(() =>
        expect(screen.getByText(/llama3\.2:3b/)).toBeTruthy(),
      );
    });

    it("renders formatted date", async () => {
      mockSummary({ generated_at: "2025-06-01T06:00:00Z" });
      renderWithQuery(<SummaryCard symbol="AAPL" />);
      await waitFor(() => {
        const text = document.body.textContent ?? "";
        expect(text).toMatch(/6\/1\/2025|01\/06\/2025|Jun.*2025/);
      });
    });
  });
});
