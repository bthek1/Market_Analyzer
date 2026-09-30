import React from "react";
import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithQuery } from "@/test/render";
import { OwnershipTab } from "@/components/companies/OwnershipTab";
import { buildOwnershipDonutOption, buildTopHoldersOption } from "@/components/companies/OwnershipTab.chartOptions";
import { MOCK_INSTITUTIONAL_HOLDERS, MOCK_SNAPSHOT } from "@/test/handlers";
import type { InstitutionalHolder } from "@/types/companies";

vi.mock("echarts-for-react", () => ({
  default: () => <div data-testid="echart" />,
}));

const BASE = "http://localhost:8004";

describe("OwnershipTab", () => {
  it("renders institutional % stat card when snapshot provided", async () => {
    renderWithQuery(<OwnershipTab companyId={1} snapshot={MOCK_SNAPSHOT} />);
    await waitFor(() => expect(screen.getByText("Institutional Ownership")).toBeTruthy());
    // 0.607 * 100 = 60.70%
    expect(screen.getByText("60.70%")).toBeTruthy();
  });

  it("renders insider % stat card", async () => {
    renderWithQuery(<OwnershipTab companyId={1} snapshot={MOCK_SNAPSHOT} />);
    await waitFor(() => expect(screen.getByText("Insider Ownership")).toBeTruthy());
    expect(screen.getByText("2.70%")).toBeTruthy();
  });

  it("renders holder names in the table", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/institutional-holders/`, () =>
        HttpResponse.json(MOCK_INSTITUTIONAL_HOLDERS),
      ),
    );
    renderWithQuery(<OwnershipTab companyId={1} snapshot={null} />);
    await waitFor(() => expect(screen.getByText("Vanguard Group Inc")).toBeTruthy());
    expect(screen.getByText("BlackRock Inc.")).toBeTruthy();
  });

  it("renders % Out values", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/institutional-holders/`, () =>
        HttpResponse.json(MOCK_INSTITUTIONAL_HOLDERS),
      ),
    );
    renderWithQuery(<OwnershipTab companyId={1} snapshot={null} />);
    await waitFor(() => expect(screen.getByText("8.31%")).toBeTruthy());
  });

  it("shows no data message when holders list is empty", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/institutional-holders/`, () =>
        HttpResponse.json({ id: "x", company: 1, fetched_at: "2026-01-01T00:00:00Z", holders: [] }),
      ),
    );
    renderWithQuery(<OwnershipTab companyId={1} snapshot={null} />);
    await waitFor(() =>
      expect(screen.getByText("No institutional holder data available.")).toBeTruthy(),
    );
  });

  it("renders fetched_at as last updated date", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/institutional-holders/`, () =>
        HttpResponse.json(MOCK_INSTITUTIONAL_HOLDERS),
      ),
    );
    renderWithQuery(<OwnershipTab companyId={1} snapshot={null} />);
    await waitFor(() => expect(screen.getByText(/Last updated: 2026-05-28/)).toBeTruthy());
  });
});

describe("buildOwnershipDonutOption", () => {
  it("returns a pie series with 3 slices", () => {
    const option = buildOwnershipDonutOption(MOCK_SNAPSHOT);
    expect(option).not.toBeNull();
    const series = option!.series as { data: { name: string; value: number }[] }[];
    expect(series[0].data).toHaveLength(3);
  });

  it("slices sum to ~100", () => {
    const option = buildOwnershipDonutOption(MOCK_SNAPSHOT);
    const series = option!.series as { data: { value: number }[] }[];
    const total = series[0].data.reduce((acc, d) => acc + d.value, 0);
    expect(total).toBeCloseTo(100, 0);
  });

  it("public float is non-negative", () => {
    const option = buildOwnershipDonutOption(MOCK_SNAPSHOT);
    const series = option!.series as { data: { name: string; value: number }[] }[];
    const pub = series[0].data.find((d) => d.name === "Public Float")!;
    expect(pub.value).toBeGreaterThanOrEqual(0);
  });

  it("returns null when both institution and insider values are null", () => {
    const snap = { ...MOCK_SNAPSHOT, held_pct_institutions: null, held_pct_insiders: null };
    expect(buildOwnershipDonutOption(snap)).toBeNull();
  });
});

describe("buildTopHoldersOption", () => {
  const holders: InstitutionalHolder[] = [
    { holder: "Vanguard", shares: 1000, date_reported: "2026-03-31", pct_out: 0.08, value: 1000 },
    { holder: "BlackRock", shares: 900, date_reported: "2026-03-31", pct_out: 0.07, value: 900 },
    { holder: "State Street", shares: 500, date_reported: "2026-03-31", pct_out: 0.04, value: 500 },
  ];

  it("returns a horizontal bar series", () => {
    const option = buildTopHoldersOption(holders);
    const series = option.series as { type: string }[];
    expect(series[0].type).toBe("bar");
  });

  it("yAxis has holder names", () => {
    const option = buildTopHoldersOption(holders);
    const yAxis = option.yAxis as { data: string[] };
    expect(yAxis.data).toContain("Vanguard");
  });

  it("limits to top 10 holders", () => {
    const many = Array.from({ length: 15 }, (_, i) => ({
      holder: `Holder ${i}`,
      shares: 1000 - i,
      date_reported: "2026-03-31",
      pct_out: (15 - i) / 100,
      value: 1000,
    }));
    const option = buildTopHoldersOption(many);
    const series = option.series as { data: number[] }[];
    expect(series[0].data).toHaveLength(10);
  });
});
