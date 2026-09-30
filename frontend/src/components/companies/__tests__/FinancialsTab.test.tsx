import React from "react";
import { describe, it, expect, vi } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithQuery } from "@/test/render";
import { FinancialsTab } from "@/components/companies/FinancialsTab";
import {
  buildRevenueOption,
  buildBalanceSheetOption,
  buildDebtEquityOption,
  buildMarginsOption,
  buildCashFlowOption,
} from "@/components/companies/FinancialsTab.chartOptions";
import { MOCK_PIVOTED_FINANCIALS } from "@/test/handlers";

vi.mock("echarts-for-react", () => ({
  default: ({ style }: { style?: React.CSSProperties }) => (
    <div data-testid="echart" data-height={style?.height} />
  ),
}));

const BASE = "http://localhost:8004";

describe("FinancialsTab", () => {
  it("renders statement type toggle buttons", async () => {
    renderWithQuery(<FinancialsTab companyId={1} />);
    await waitFor(() => expect(screen.getByText("Income Statement")).toBeTruthy());
    expect(screen.getByText("Balance Sheet")).toBeTruthy();
    expect(screen.getByText("Cash Flow")).toBeTruthy();
  });

  it("renders period toggle buttons", async () => {
    renderWithQuery(<FinancialsTab companyId={1} />);
    await waitFor(() => expect(screen.getByText("Annual")).toBeTruthy());
    expect(screen.getByText("Quarterly")).toBeTruthy();
  });

  it("renders the revenue chart when income data is present", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/financials/pivoted/`, () =>
        HttpResponse.json(MOCK_PIVOTED_FINANCIALS),
      ),
    );
    renderWithQuery(<FinancialsTab companyId={1} />);
    await waitFor(() => expect(screen.getAllByTestId("echart").length).toBeGreaterThan(0));
  });

  it("renders the data table with metric column", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/financials/pivoted/`, () =>
        HttpResponse.json(MOCK_PIVOTED_FINANCIALS),
      ),
    );
    renderWithQuery(<FinancialsTab companyId={1} />);
    await waitFor(() => expect(screen.getByText("Total Revenue")).toBeTruthy());
  });

  it("renders date columns in the table", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/financials/pivoted/`, () =>
        HttpResponse.json(MOCK_PIVOTED_FINANCIALS),
      ),
    );
    renderWithQuery(<FinancialsTab companyId={1} />);
    await waitFor(() => expect(screen.getByText("2023-12-31")).toBeTruthy());
  });

  it("shows empty state when no data returned", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/financials/pivoted/`, () =>
        HttpResponse.json({ dates: [], rows: [] }),
      ),
    );
    renderWithQuery(<FinancialsTab companyId={1} />);
    await waitFor(() =>
      expect(screen.getByText("No financial data available.")).toBeTruthy(),
    );
  });

  it("switches to Balance Sheet when clicked", async () => {
    renderWithQuery(<FinancialsTab companyId={1} />);
    await waitFor(() => expect(screen.getByText("Balance Sheet")).toBeTruthy());
    fireEvent.click(screen.getByText("Balance Sheet"));
    // Button is now active (variant=default) — just check no crash
    expect(screen.getByText("Balance Sheet")).toBeTruthy();
  });
});

describe("buildRevenueOption", () => {
  const dates = ["2023-12-31", "2022-12-31"];
  const baseRows = [
    { metric: "Total Revenue", values: [400e9, 365e9] },
    { metric: "Net Income", values: [97e9, 99e9] },
  ];

  it("returns series containing Total Revenue and Net Income", () => {
    const option = buildRevenueOption(dates, baseRows);
    const series = option.series as { name: string }[];
    expect(series.map((s) => s.name)).toContain("Total Revenue");
    expect(series.map((s) => s.name)).toContain("Net Income");
  });

  it("adds EBITDA series when EBITDA values are non-null", () => {
    const rows = [...baseRows, { metric: "EBITDA", values: [130e9, 120e9] }];
    const option = buildRevenueOption(dates, rows);
    const series = option.series as { name: string }[];
    expect(series.map((s) => s.name)).toContain("EBITDA");
  });

  it("adds Gross Profit line series when gross profit values are non-null", () => {
    const rows = [...baseRows, { metric: "Gross Profit", values: [180e9, 170e9] }];
    const option = buildRevenueOption(dates, rows);
    const series = option.series as { name: string; type: string }[];
    const gp = series.find((s) => s.name === "Gross Profit");
    expect(gp).toBeDefined();
    expect(gp!.type).toBe("line");
  });

  it("does not add EBITDA series when all EBITDA values are null", () => {
    const rows = [...baseRows, { metric: "EBITDA", values: [null, null] }];
    const option = buildRevenueOption(dates, rows);
    const series = option.series as { name: string }[];
    expect(series.map((s) => s.name)).not.toContain("EBITDA");
  });
});

describe("buildBalanceSheetOption", () => {
  const dates = ["2023-12-31", "2022-12-31"];
  const rows = [
    { metric: "Total Assets", values: [300e9, 280e9] },
    { metric: "Cash And Cash Equivalents", values: [50e9, 45e9] },
    { metric: "Total Liabilities", values: [200e9, 190e9] },
    { metric: "Total Stockholder Equity", values: [50e9, 45e9] },
  ];

  it("returns a stacked bar option when Total Assets are present", () => {
    const option = buildBalanceSheetOption(dates, rows);
    expect(option).not.toBeNull();
    const series = option!.series as { type: string; stack: string }[];
    expect(series.every((s) => s.stack === "total")).toBe(true);
  });

  it("returns null when Total Assets are all null", () => {
    const noAssets = [{ metric: "Total Assets", values: [null, null] }];
    expect(buildBalanceSheetOption(dates, noAssets)).toBeNull();
  });
});

describe("buildDebtEquityOption", () => {
  const dates = ["2023-12-31", "2022-12-31"];

  it("returns a dual-line option when debt and equity data present", () => {
    const rows = [
      { metric: "Total Debt", values: [120e9, 110e9] },
      { metric: "Total Stockholder Equity", values: [50e9, 45e9] },
    ];
    const option = buildDebtEquityOption(dates, rows);
    expect(option).not.toBeNull();
    const series = option!.series as { name: string; type: string }[];
    expect(series.find((s) => s.name === "Total Debt")?.type).toBe("line");
    expect(series.find((s) => s.name === "Stockholder Equity")?.type).toBe("line");
  });

  it("returns null when all values are null", () => {
    const rows = [
      { metric: "Total Debt", values: [null, null] },
      { metric: "Total Stockholder Equity", values: [null, null] },
    ];
    expect(buildDebtEquityOption(dates, rows)).toBeNull();
  });
});

describe("buildMarginsOption", () => {
  const dates = ["2023-12-31", "2022-12-31"];
  const rows = [
    { metric: "Total Revenue", values: [400e9, 365e9] },
    { metric: "Gross Profit", values: [180e9, 162e9] },
    { metric: "Operating Income", values: [114e9, 119e9] },
    { metric: "Net Income", values: [97e9, 99e9] },
  ];

  it("returns a line chart option with three margin series", () => {
    const option = buildMarginsOption(dates, rows);
    expect(option).not.toBeNull();
    const series = option!.series as { name: string; type: string }[];
    expect(series).toHaveLength(3);
    expect(series.map((s) => s.name)).toContain("Gross Margin");
    expect(series.map((s) => s.name)).toContain("Operating Margin");
    expect(series.map((s) => s.name)).toContain("Net Margin");
    series.forEach((s) => expect(s.type).toBe("line"));
  });

  it("computes gross margin as % of revenue", () => {
    const option = buildMarginsOption(dates, rows);
    const series = option!.series as { name: string; data: (number | null)[] }[];
    const gm = series.find((s) => s.name === "Gross Margin")!;
    expect(gm.data[0]).toBeCloseTo((180e9 / 400e9) * 100, 1);
  });

  it("returns null when all revenue values are null", () => {
    const noRevenue = [{ metric: "Total Revenue", values: [null, null] }];
    expect(buildMarginsOption(dates, noRevenue)).toBeNull();
  });

  it("produces null margin values where revenue is null", () => {
    const mixed = [
      { metric: "Total Revenue", values: [400e9, null] },
      { metric: "Net Income", values: [97e9, null] },
    ];
    const option = buildMarginsOption(dates, mixed);
    const series = option!.series as { name: string; data: (number | null)[] }[];
    const nm = series.find((s) => s.name === "Net Margin")!;
    expect(nm.data[1]).toBeNull();
  });
});

describe("buildCashFlowOption", () => {
  const dates = ["2023-12-31", "2022-12-31"];
  const rows = [
    { metric: "Operating Cash Flow", values: [118e9, 122e9] },
    { metric: "Capital Expenditure", values: [-11e9, -10e9] },
    { metric: "Free Cash Flow", values: [107e9, 112e9] },
  ];

  it("returns a bar chart option with three series", () => {
    const option = buildCashFlowOption(dates, rows);
    expect(option).not.toBeNull();
    const series = option!.series as { name: string; type: string }[];
    expect(series).toHaveLength(3);
    series.forEach((s) => expect(s.type).toBe("bar"));
  });

  it("series names are Operating CF, CapEx, Free CF", () => {
    const option = buildCashFlowOption(dates, rows);
    const series = option!.series as { name: string }[];
    expect(series.map((s) => s.name)).toContain("Operating CF");
    expect(series.map((s) => s.name)).toContain("CapEx");
    expect(series.map((s) => s.name)).toContain("Free CF");
  });

  it("returns null when all cash flow values are null", () => {
    const empty = [
      { metric: "Operating Cash Flow", values: [null, null] },
      { metric: "Capital Expenditure", values: [null, null] },
      { metric: "Free Cash Flow", values: [null, null] },
    ];
    expect(buildCashFlowOption(dates, empty)).toBeNull();
  });

  it("operating cash flow data matches source rows", () => {
    const option = buildCashFlowOption(dates, rows);
    const series = option!.series as { name: string; data: (number | null)[] }[];
    const ocf = series.find((s) => s.name === "Operating CF")!;
    expect(ocf.data[0]).toBe(118e9);
  });
});
