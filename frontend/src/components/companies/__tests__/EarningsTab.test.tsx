import React from "react";
import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithQuery } from "@/test/render";
import { EarningsTab } from "@/components/companies/EarningsTab";
import { buildSurpriseTrendOption, buildEPSOption } from "@/components/companies/EarningsTab.chartOptions";
import {
  MOCK_EARNINGS_DATE,
  MOCK_PAGINATED_EARNINGS,
  MOCK_PAST_EARNINGS_DATE,
} from "@/test/handlers";
import type { EarningsDate } from "@/types/companies";

vi.mock("echarts-for-react", () => ({
  default: () => <div data-testid="echart" />,
}));

const BASE = "http://localhost:8004";

describe("EarningsTab", () => {
  it("renders upcoming earnings card with date", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/earnings-dates/`, () =>
        HttpResponse.json(MOCK_PAGINATED_EARNINGS),
      ),
    );
    renderWithQuery(<EarningsTab companyId={1} />);
    await waitFor(() => expect(screen.getByText("Upcoming Earnings")).toBeTruthy());
    // date appears in both the upcoming card and the table
    expect(screen.getAllByText(MOCK_EARNINGS_DATE.earnings_date).length).toBeGreaterThan(0);
  });

  it("shows EPS estimate for upcoming earnings", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/earnings-dates/`, () =>
        HttpResponse.json(MOCK_PAGINATED_EARNINGS),
      ),
    );
    renderWithQuery(<EarningsTab companyId={1} />);
    await waitFor(() => expect(screen.getByText(/EPS Estimate:/)).toBeTruthy());
    // 1.42 appears in the upcoming card span and in the table cell
    expect(screen.getAllByText("1.42").length).toBeGreaterThan(0);
  });

  it("renders EPS history chart for historical records", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/earnings-dates/`, () =>
        HttpResponse.json(MOCK_PAGINATED_EARNINGS),
      ),
    );
    renderWithQuery(<EarningsTab companyId={1} />);
    await waitFor(() => expect(screen.getAllByTestId("echart").length).toBeGreaterThan(0));
  });

  it("renders earnings calendar table", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/earnings-dates/`, () =>
        HttpResponse.json(MOCK_PAGINATED_EARNINGS),
      ),
    );
    const { container } = renderWithQuery(<EarningsTab companyId={1} />);
    await waitFor(() => expect(container.querySelector("table")).toBeTruthy());
  });

  it("shows reported EPS for past earnings", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/earnings-dates/`, () =>
        HttpResponse.json(MOCK_PAGINATED_EARNINGS),
      ),
    );
    renderWithQuery(<EarningsTab companyId={1} />);
    await waitFor(() =>
      expect(screen.getByText(MOCK_PAST_EARNINGS_DATE.reported_eps!.toFixed(2))).toBeTruthy(),
    );
  });

  it("shows surprise % for past earnings", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/earnings-dates/`, () =>
        HttpResponse.json(MOCK_PAGINATED_EARNINGS),
      ),
    );
    renderWithQuery(<EarningsTab companyId={1} />);
    await waitFor(() => expect(screen.getByText("2.48%")).toBeTruthy());
  });

  it("shows empty state when no data", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/earnings-dates/`, () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
    );
    renderWithQuery(<EarningsTab companyId={1} />);
    await waitFor(() =>
      expect(screen.getByText("No earnings data available.")).toBeTruthy(),
    );
  });
});

describe("buildSurpriseTrendOption", () => {
  const makeRecord = (date: string, surprise: number | null): EarningsDate => ({
    id: `ed-${date}`,
    company: 1,
    earnings_date: date,
    eps_estimate: 1.5,
    reported_eps: 1.6,
    surprise_pct: surprise,
    is_upcoming: false,
  });

  const records: EarningsDate[] = [
    makeRecord("2026-02-01", 2.5),
    makeRecord("2025-11-01", -1.2),
    makeRecord("2025-08-01", 3.1),
  ];

  it("returns an option with a bar series", () => {
    const option = buildSurpriseTrendOption(records);
    expect(option).not.toBeNull();
    const series = option!.series as { type: string }[];
    expect(series[0].type).toBe("bar");
  });

  it("x axis contains dates in chronological order", () => {
    const option = buildSurpriseTrendOption(records);
    const xAxis = option!.xAxis as { data: string[] };
    expect(xAxis.data[0]).toBe("2025-08-01");
    expect(xAxis.data[2]).toBe("2026-02-01");
  });

  it("series data matches surprise_pct values", () => {
    const option = buildSurpriseTrendOption(records);
    const series = option!.series as { data: { value: number | null }[] }[];
    expect(series[0].data.map((d) => d.value)).toContain(3.1);
    expect(series[0].data.map((d) => d.value)).toContain(-1.2);
  });

  it("positive surprise bars are green, negative are red", () => {
    const option = buildSurpriseTrendOption(records);
    const series = option!.series as { data: { value: number; itemStyle: { color: string } }[] }[];
    const items = series[0].data;
    const positive = items.find((d) => d.value > 0)!;
    const negative = items.find((d) => d.value < 0)!;
    expect(positive.itemStyle.color).toBe("#16a34a");
    expect(negative.itemStyle.color).toBe("#ef4444");
  });

  it("includes a zero reference markLine", () => {
    const option = buildSurpriseTrendOption(records);
    const series = option!.series as { markLine?: { data: { yAxis: number }[] } }[];
    expect(series[0].markLine?.data[0].yAxis).toBe(0);
  });

  it("returns null when no records with non-null surprise", () => {
    expect(buildSurpriseTrendOption([])).toBeNull();
    expect(buildSurpriseTrendOption([makeRecord("2026-02-01", null)])).toBeNull();
  });

  it("skips records with null surprise_pct", () => {
    const withNull = [...records, makeRecord("2024-05-01", null)];
    const option = buildSurpriseTrendOption(withNull);
    const series = option!.series as { data: { value: number | null }[] }[];
    expect(series[0].data.map((d) => d.value)).not.toContain(null);
  });
});

describe("buildEPSOption", () => {
  const makeRecord = (
    date: string,
    estimate: number | null,
    reported: number | null,
    upcoming = false,
  ): EarningsDate => ({
    id: `ed-${date}`,
    company: 1,
    earnings_date: date,
    eps_estimate: estimate,
    reported_eps: reported,
    surprise_pct: null,
    is_upcoming: upcoming,
  });

  const past: EarningsDate[] = [
    makeRecord("2025-08-01", 1.40, 1.45),
    makeRecord("2025-11-01", 1.55, 1.61),
    makeRecord("2026-02-01", 1.60, 1.65),
  ];

  it("returns an option with two bar series (estimate and reported)", () => {
    const option = buildEPSOption(past);
    const series = option.series as { name: string; type: string }[];
    expect(series).toHaveLength(2);
    expect(series.map((s) => s.name)).toContain("EPS Estimate");
    expect(series.map((s) => s.name)).toContain("Reported EPS");
    series.forEach((s) => expect(s.type).toBe("bar"));
  });

  it("reverses the slice so the last input record appears first on x axis", () => {
    const option = buildEPSOption(past);
    const xAxis = option.xAxis as { data: string[] };
    expect(xAxis.data[0]).toBe("2026-02-01");
  });

  it("excludes upcoming records", () => {
    const withUpcoming = [
      ...past,
      makeRecord("2026-07-31", 1.70, null, true),
    ];
    const option = buildEPSOption(withUpcoming);
    const xAxis = option.xAxis as { data: string[] };
    expect(xAxis.data).not.toContain("2026-07-31");
  });

  it("estimate series data length matches x axis length", () => {
    const option = buildEPSOption(past);
    const xAxis = option.xAxis as { data: string[] };
    const series = option.series as { name: string; data: unknown[] }[];
    const est = series.find((s) => s.name === "EPS Estimate")!;
    expect(est.data).toHaveLength(xAxis.data.length);
  });

  it("reported EPS item is green when reported >= estimate", () => {
    const option = buildEPSOption(past);
    const series = option.series as {
      name: string;
      data: { value: number; itemStyle: { color: string } }[];
    }[];
    const rep = series.find((s) => s.name === "Reported EPS")!;
    expect(rep.data[0].itemStyle.color).toBe("#16a34a");
  });

  it("reported EPS item is red when reported < estimate", () => {
    const miss: EarningsDate[] = [
      makeRecord("2026-02-01", 1.70, 1.55),
      makeRecord("2025-11-01", 1.60, 1.58),
    ];
    const option = buildEPSOption(miss);
    const series = option.series as {
      name: string;
      data: { value: number; itemStyle: { color: string } }[];
    }[];
    const rep = series.find((s) => s.name === "Reported EPS")!;
    expect(rep.data[0].itemStyle.color).toBe("#ef4444");
  });
});
