import React from "react";
import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithQuery } from "@/test/render";
import { SummaryProgressWidget } from "@/components/companies/SummaryProgressWidget";

vi.mock("echarts-for-react", () => ({
  default: () => <div data-testid="echart" />,
}));

const BASE = "http://localhost:8004";

const MOCK_FRESHNESS = {
  total_companies: 100,
  buckets: {
    lt_1h: 10,
    h1_6: 5,
    h6_24: 15,
    d1_7: 20,
    d7_30: 25,
    gt_30d: 5,
    never: 20,
  },
};

function mockFreshness(payload = MOCK_FRESHNESS) {
  server.use(
    http.get(`${BASE}/api/companies/summary-freshness/`, () => HttpResponse.json(payload)),
  );
}

describe("SummaryProgressWidget", () => {
  it("renders skeleton while loading", () => {
    server.use(
      http.get(`${BASE}/api/companies/summary-freshness/`, async () => {
        await new Promise(() => {}); // never resolves
        return HttpResponse.json(MOCK_FRESHNESS);
      }),
    );
    const { container } = renderWithQuery(<SummaryProgressWidget />);
    expect(container.querySelector(".animate-pulse")).toBeTruthy();
  });

  it("renders the card title after loading", async () => {
    mockFreshness();
    renderWithQuery(<SummaryProgressWidget />);
    await waitFor(() => expect(screen.getByText("AI Summary Generation")).toBeTruthy());
  });

  it("shows total_companies in the description", async () => {
    mockFreshness();
    renderWithQuery(<SummaryProgressWidget />);
    await waitFor(() =>
      expect(screen.getByText(/100 tracked companies/)).toBeTruthy(),
    );
  });

  it("renders the chart when data is available", async () => {
    mockFreshness();
    const { container } = renderWithQuery(<SummaryProgressWidget />);
    await waitFor(() =>
      expect(container.querySelector(".animate-pulse")).toBeNull(),
    );
    // echarts-for-react renders a canvas element once data arrives
    expect(screen.getByText("AI Summary Generation")).toBeTruthy();
  });

  it("shows dash for total when still loading", () => {
    server.use(
      http.get(`${BASE}/api/companies/summary-freshness/`, async () => {
        await new Promise(() => {});
        return HttpResponse.json(MOCK_FRESHNESS);
      }),
    );
    renderWithQuery(<SummaryProgressWidget />);
    expect(screen.getByText(/—/)).toBeTruthy();
  });

  it("shows correct total_companies when all are generated", async () => {
    mockFreshness({
      total_companies: 50,
      buckets: { lt_1h: 50, h1_6: 0, h6_24: 0, d1_7: 0, d7_30: 0, gt_30d: 0, never: 0 },
    });
    renderWithQuery(<SummaryProgressWidget />);
    await waitFor(() => expect(screen.getByText(/50 tracked companies/)).toBeTruthy());
  });

  it("shows correct total_companies when none are generated", async () => {
    mockFreshness({
      total_companies: 30,
      buckets: { lt_1h: 0, h1_6: 0, h6_24: 0, d1_7: 0, d7_30: 0, gt_30d: 0, never: 30 },
    });
    renderWithQuery(<SummaryProgressWidget />);
    await waitFor(() => expect(screen.getByText(/30 tracked companies/)).toBeTruthy());
  });
});
