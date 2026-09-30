import React from "react";
import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";
import { OverviewTab } from "@/components/companies/OverviewTab";
import { buildRadarOption } from "@/components/companies/OverviewTab.chartOptions";
import { MOCK_COMPANY, MOCK_SNAPSHOT } from "@/test/handlers";
import type { CompanySnapshot } from "@/types/companies";

vi.mock("echarts-for-react", () => ({
  default: () => <div data-testid="echart" />,
}));

describe("OverviewTab", () => {
  it("renders company description", () => {
    renderWithQuery(<OverviewTab company={MOCK_COMPANY} snapshot={MOCK_SNAPSHOT} />);
    expect(screen.getByText(/Apple Inc\. designs/)).toBeTruthy();
  });

  it("renders full_time_employees", () => {
    renderWithQuery(<OverviewTab company={MOCK_COMPANY} snapshot={MOCK_SNAPSHOT} />);
    expect(screen.getByText("164,000")).toBeTruthy();
  });

  it("renders city and country as headquarters", () => {
    renderWithQuery(<OverviewTab company={MOCK_COMPANY} snapshot={MOCK_SNAPSHOT} />);
    expect(screen.getByText("Cupertino, CA, United States")).toBeTruthy();
  });

  it("renders website as a link", () => {
    const { container } = renderWithQuery(
      <OverviewTab company={MOCK_COMPANY} snapshot={MOCK_SNAPSHOT} />,
    );
    const link = container.querySelector('a[href="https://www.apple.com"]');
    expect(link).toBeTruthy();
  });

  it("renders officer name in leadership table", () => {
    renderWithQuery(<OverviewTab company={MOCK_COMPANY} snapshot={MOCK_SNAPSHOT} />);
    expect(screen.getByText("Timothy D. Cook")).toBeTruthy();
  });

  it("renders officer title", () => {
    renderWithQuery(<OverviewTab company={MOCK_COMPANY} snapshot={MOCK_SNAPSHOT} />);
    expect(screen.getByText("CEO & Director")).toBeTruthy();
  });

  it("renders sector stat card", () => {
    renderWithQuery(<OverviewTab company={MOCK_COMPANY} snapshot={MOCK_SNAPSHOT} />);
    expect(screen.getByText("Technology")).toBeTruthy();
  });

  it("renders market cap stat card", () => {
    renderWithQuery(<OverviewTab company={MOCK_COMPANY} snapshot={MOCK_SNAPSHOT} />);
    expect(screen.getByText("3T")).toBeTruthy();
  });

  it("renders trailing P/E", () => {
    renderWithQuery(<OverviewTab company={MOCK_COMPANY} snapshot={MOCK_SNAPSHOT} />);
    expect(screen.getByText("28.5")).toBeTruthy();
  });

  it("renders governance risk bars", () => {
    renderWithQuery(<OverviewTab company={MOCK_COMPANY} snapshot={MOCK_SNAPSHOT} />);
    expect(screen.getByText("Overall Risk")).toBeTruthy();
    expect(screen.getByText("Audit Risk")).toBeTruthy();
  });

  it("renders analyst recommendation badge", () => {
    renderWithQuery(<OverviewTab company={MOCK_COMPANY} snapshot={MOCK_SNAPSHOT} />);
    expect(screen.getByText("BUY")).toBeTruthy();
  });

  it("renders at least one echart when breakdown is non-empty", () => {
    renderWithQuery(<OverviewTab company={MOCK_COMPANY} snapshot={MOCK_SNAPSHOT} />);
    expect(screen.getAllByTestId("echart").length).toBeGreaterThanOrEqual(1);
  });

  it("renders 'No snapshot data available' when snapshot is null", () => {
    renderWithQuery(<OverviewTab company={MOCK_COMPANY} snapshot={null} />);
    expect(screen.getByText("No snapshot data available.")).toBeTruthy();
  });

  it("truncates long descriptions and shows 'Show more' button", () => {
    const longDesc = "A".repeat(500);
    const company = { ...MOCK_COMPANY, description: longDesc };
    renderWithQuery(<OverviewTab company={company} snapshot={null} />);
    expect(screen.getByText("Show more")).toBeTruthy();
  });

  it("expands description when 'Show more' is clicked", () => {
    const longDesc = "A".repeat(500);
    const company = { ...MOCK_COMPANY, description: longDesc };
    renderWithQuery(<OverviewTab company={company} snapshot={null} />);
    fireEvent.click(screen.getByText("Show more"));
    expect(screen.getByText("Show less")).toBeTruthy();
  });

  it("renders split factor from snapshot", () => {
    renderWithQuery(<OverviewTab company={MOCK_COMPANY} snapshot={MOCK_SNAPSHOT} />);
    expect(screen.getByText("4:1")).toBeTruthy();
  });

  it("renders 52-week range bar when 52W low/high present", () => {
    renderWithQuery(<OverviewTab company={MOCK_COMPANY} snapshot={MOCK_SNAPSHOT} />);
    expect(screen.getByText("52-Week Price Range")).toBeTruthy();
  });

  it("renders analyst price target range bar when target prices present", () => {
    renderWithQuery(<OverviewTab company={MOCK_COMPANY} snapshot={MOCK_SNAPSHOT} />);
    expect(screen.getByText("Analyst Price Target Range")).toBeTruthy();
  });

  it("renders radar chart section when snapshot has sufficient metrics", () => {
    renderWithQuery(<OverviewTab company={MOCK_COMPANY} snapshot={MOCK_SNAPSHOT} />);
    expect(screen.getByText("Performance Overview")).toBeTruthy();
  });
});

describe("buildRadarOption", () => {
  const base: CompanySnapshot = {
    ...MOCK_SNAPSHOT,
    gross_margins: 0.45,
    operating_margins: 0.3,
    profit_margins: 0.25,
    return_on_equity: 1.47,
    return_on_assets: 0.22,
    revenue_growth: 0.05,
  };

  it("returns an option with radar indicator array of length 6", () => {
    const option = buildRadarOption(base);
    expect(option).not.toBeNull();
    const radar = option!.radar as { indicator: unknown[] };
    expect(radar.indicator).toHaveLength(6);
  });

  it("returns a radar series with value length 6", () => {
    const option = buildRadarOption(base);
    const series = (option!.series as { data: { value: number[] }[] }[])[0];
    expect(series.data[0].value).toHaveLength(6);
  });

  it("clamps normalised values to [0, 100]", () => {
    const snap = { ...base, return_on_equity: 5.0 };
    const option = buildRadarOption(snap);
    const series = (option!.series as { data: { value: number[] }[] }[])[0];
    series.data[0].value.forEach((v) => {
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(100);
    });
  });

  it("returns null when fewer than 3 non-null metrics", () => {
    const sparse: CompanySnapshot = {
      ...base,
      gross_margins: null,
      operating_margins: null,
      profit_margins: null,
      return_on_equity: null,
      return_on_assets: null,
    };
    expect(buildRadarOption(sparse)).toBeNull();
  });
});
