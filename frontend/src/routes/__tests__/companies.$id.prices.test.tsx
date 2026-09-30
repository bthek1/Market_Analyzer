import React from "react";
import { describe, it, expect, vi } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithQuery } from "@/test/render";
import { MarketDataTab } from "@/components/companies/MarketDataTab";
import type { PriceBar, PaginatedResponse } from "@/types/companies";

vi.mock("echarts-for-react", () => ({
  default: () => <div data-testid="echart" />,
}));

const BASE = "http://localhost:8004";

const makeBar = (i: number): PriceBar => ({
  id: i,
  company: 1,
  date: `2024-01-${String(i).padStart(2, "0")}`,
  open: "100.00",
  high: "105.00",
  low: "99.00",
  close: "102.00",
  volume: 1_000_000,
});

// Builds two bars so PriceChart doesn't bail out early.
const CHART_RESPONSE: PaginatedResponse<PriceBar> = {
  count: 10,
  next: null,
  previous: null,
  results: [makeBar(1), makeBar(2)],
};

// 5 rows for the paginated table, count=10 → 2 pages.
const PAGE_1_RESPONSE: PaginatedResponse<PriceBar> = {
  count: 10,
  next: "next",
  previous: null,
  results: Array.from({ length: 5 }, (_, i) => makeBar(i + 1)),
};

const PAGE_2_RESPONSE: PaginatedResponse<PriceBar> = {
  count: 10,
  next: null,
  previous: "prev",
  results: Array.from({ length: 5 }, (_, i) => makeBar(i + 6)),
};

// Handler that distinguishes the chart request (no page_size) from the table request.
function setupPriceHandlers() {
  server.use(
    http.get(`${BASE}/api/companies/:id/prices/`, ({ request }) => {
      const params = new URL(request.url).searchParams;
      const pageSize = params.get("page_size");
      const page = params.get("page");

      if (pageSize === "5") {
        return HttpResponse.json(page === "2" ? PAGE_2_RESPONSE : PAGE_1_RESPONSE);
      }
      return HttpResponse.json(CHART_RESPONSE);
    }),
    http.get(`${BASE}/api/companies/:id/short-interest/`, () =>
      HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
    ),
  );
}

describe("PricesSection", () => {
  it("renders empty state when API returns no bars", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/prices/`, () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
      http.get(`${BASE}/api/companies/:id/short-interest/`, () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
    );
    renderWithQuery(<MarketDataTab companyId={1} snapshot={null} />);
    await waitFor(() =>
      expect(screen.getByText("No price history available.")).toBeTruthy(),
    );
  });

  it("renders the candlestick chart when bars are present", async () => {
    setupPriceHandlers();
    renderWithQuery(<MarketDataTab companyId={1} snapshot={null} />);
    await waitFor(() => expect(screen.getByTestId("echart")).toBeTruthy());
  });

  it("shows correct page label on first load", async () => {
    setupPriceHandlers();
    renderWithQuery(<MarketDataTab companyId={1} snapshot={null} />);
    await waitFor(() => expect(screen.getByText("Page 1 of 2")).toBeTruthy());
  });

  it("disables Prev button on page 1", async () => {
    setupPriceHandlers();
    renderWithQuery(<MarketDataTab companyId={1} snapshot={null} />);
    await waitFor(() => expect(screen.getByText("Page 1 of 2")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Prev" })).toBeDisabled();
  });

  it("enables Next button when there are multiple pages", async () => {
    setupPriceHandlers();
    renderWithQuery(<MarketDataTab companyId={1} snapshot={null} />);
    await waitFor(() => expect(screen.getByText("Page 1 of 2")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Next" })).not.toBeDisabled();
  });

  it("advances to page 2 when Next is clicked", async () => {
    setupPriceHandlers();
    renderWithQuery(<MarketDataTab companyId={1} snapshot={null} />);
    await waitFor(() => expect(screen.getByText("Page 1 of 2")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(screen.getByText("Page 2 of 2")).toBeTruthy());
  });

  it("disables Next on the last page", async () => {
    setupPriceHandlers();
    renderWithQuery(<MarketDataTab companyId={1} snapshot={null} />);
    await waitFor(() => expect(screen.getByText("Page 1 of 2")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(screen.getByText("Page 2 of 2")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("returns to page 1 when Prev is clicked from page 2", async () => {
    setupPriceHandlers();
    renderWithQuery(<MarketDataTab companyId={1} snapshot={null} />);
    await waitFor(() => expect(screen.getByText("Page 1 of 2")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(screen.getByText("Page 2 of 2")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Prev" }));
    await waitFor(() => expect(screen.getByText("Page 1 of 2")).toBeTruthy());
  });

  it("shows Page 1 of 1 and disables both buttons when count equals page size", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/prices/`, ({ request }) => {
        const params = new URL(request.url).searchParams;
        if (params.get("page_size") === "5") {
          return HttpResponse.json({
            count: 5,
            next: null,
            previous: null,
            results: Array.from({ length: 5 }, (_, i) => makeBar(i + 1)),
          });
        }
        return HttpResponse.json(CHART_RESPONSE);
      }),
      http.get(`${BASE}/api/companies/:id/short-interest/`, () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
    );
    renderWithQuery(<MarketDataTab companyId={1} snapshot={null} />);
    await waitFor(() => expect(screen.getByText("Page 1 of 1")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Prev" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });
});
