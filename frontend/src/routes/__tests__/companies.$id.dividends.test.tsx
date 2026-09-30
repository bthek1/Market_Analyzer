import React from "react";
import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithQuery } from "@/test/render";
import { DividendsTab } from "@/components/companies/DividendsTab";
import type { Dividend, PaginatedResponse } from "@/types/companies";

vi.mock("echarts-for-react", () => ({
  default: ({ style }: { style?: React.CSSProperties }) => (
    <div data-testid="echart" data-height={style?.height} />
  ),
}));

const BASE = "http://localhost:8004";

const makeDividend = (i: number): Dividend => ({
  id: i,
  company: 1,
  date: `2024-0${i}-01`,
  amount: "0.2500",
});

const DIVIDENDS_RESPONSE: PaginatedResponse<Dividend> = {
  count: 4,
  next: null,
  previous: null,
  results: [makeDividend(1), makeDividend(2), makeDividend(3), makeDividend(4)],
};

describe("DividendsTab", () => {
  it("shows empty state when there are no dividends", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/dividends/`, () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
    );
    renderWithQuery(<DividendsTab companyId={1} snapshot={null} />);
    await waitFor(() =>
      expect(screen.getByText("No dividend data available.")).toBeTruthy(),
    );
  });

  it("renders the chart when dividends are present", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/dividends/`, () =>
        HttpResponse.json(DIVIDENDS_RESPONSE),
      ),
    );
    renderWithQuery(<DividendsTab companyId={1} snapshot={null} />);
    await waitFor(() => expect(screen.getByTestId("echart")).toBeTruthy());
  });

  it("renders the per-payment history chart at height 200", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/dividends/`, () =>
        HttpResponse.json(DIVIDENDS_RESPONSE),
      ),
    );
    renderWithQuery(<DividendsTab companyId={1} snapshot={null} />);
    await waitFor(() => expect(screen.getByTestId("echart")).toBeTruthy());
    expect(screen.getByTestId("echart")).toHaveAttribute("data-height", "200");
  });

  it("renders a table with dividend rows", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/dividends/`, () =>
        HttpResponse.json(DIVIDENDS_RESPONSE),
      ),
    );
    const { container } = renderWithQuery(<DividendsTab companyId={1} snapshot={null} />);
    await waitFor(() => expect(screen.getByTestId("echart")).toBeTruthy());
    expect(container.querySelector("table")).toBeTruthy();
  });

  it("shows no chart when only one dividend exists", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/dividends/`, () =>
        HttpResponse.json({
          count: 1,
          next: null,
          previous: null,
          results: [makeDividend(1)],
        }),
      ),
    );
    const { container } = renderWithQuery(<DividendsTab companyId={1} snapshot={null} />);
    await waitFor(() => expect(container.querySelector("[data-testid='echart']")).toBeNull());
  });
});
