import React from "react";
import { describe, it, expect, vi } from "vitest";
import { renderWithQuery } from "@/test/render";
import { SectorIndustryTreemap } from "@/components/companies/SectorIndustryTreemap";
import { buildTreemapOption } from "@/components/companies/SectorIndustryTreemap.chartOptions";

vi.mock("echarts-for-react", () => ({
  default: ({ onEvents }: { onEvents?: Record<string, (p: unknown) => void> }) => (
    <div
      data-testid="echart"
      onClick={() =>
        onEvents?.["click"]?.({
          data: { name: "Healthcare" },
          treePathInfo: [null],
        })
      }
    />
  ),
}));

const DATA = [
  {
    name: "Technology",
    value: 15,
    company_count: 15,
    market_cap: 2_000_000_000,
    children: [
      { name: "Software", value: 10, company_count: 10, market_cap: 1_200_000_000 },
      { name: "Hardware", value: 5, company_count: 5, market_cap: 800_000_000 },
    ],
  },
  {
    name: "Healthcare",
    value: 8,
    company_count: 8,
    market_cap: 500_000_000,
    children: [{ name: "Biotech", value: 8, company_count: 8, market_cap: 500_000_000 }],
  },
];

describe("buildTreemapOption", () => {
  it("returns treemap series type", () => {
    const option = buildTreemapOption(DATA);
    const series = (option.series as { type: string }[])[0];
    expect(series.type).toBe("treemap");
  });

  it("passes data through to series", () => {
    const option = buildTreemapOption(DATA);
    const series = (option.series as { data: typeof DATA }[])[0];
    expect(series.data).toBe(DATA);
  });

  it("enables breadcrumb", () => {
    const option = buildTreemapOption(DATA);
    const series = (option.series as { breadcrumb: { show: boolean } }[])[0];
    expect(series.breadcrumb.show).toBe(true);
  });

  it("upperLabel uses dark text color", () => {
    const option = buildTreemapOption(DATA);
    const series = (option.series as { upperLabel: { color: string } }[])[0];
    expect(series.upperLabel.color).toBe("#1f2937");
  });

  it("series is pinned to all four edges with explicit left/right/bottom", () => {
    const option = buildTreemapOption(DATA);
    const series = (option.series as { left: number; right: number; bottom: number }[])[0];
    expect(series.left).toBe(0);
    expect(series.right).toBe(0);
    expect(series.bottom).toBe(0);
  });

  it("series top is 32 to sit below the breadcrumb band", () => {
    const option = buildTreemapOption(DATA);
    const series = (option.series as { top: number }[])[0];
    expect(series.top).toBe(32);
  });
});

describe("buildTreemapOption market_cap mode", () => {
  it("tooltip formatter shows market cap value in market_cap mode", () => {
    const option = buildTreemapOption(DATA, "market_cap");
    const formatter = (option.tooltip as { formatter: (p: unknown) => string }).formatter;
    const html = formatter({ data: DATA[0] });
    expect(html).toContain("$2.0B");
    expect(html).toContain("15 companies");
  });

  it("tooltip formatter shows company count in count mode", () => {
    const option = buildTreemapOption(DATA, "count");
    const formatter = (option.tooltip as { formatter: (p: unknown) => string }).formatter;
    const html = formatter({ data: DATA[0] });
    expect(html).toContain("15 companies");
    expect(html).not.toContain("$");
  });
});

describe("SectorIndustryTreemap", () => {
  it("renders without crash", () => {
    const { getByTestId } = renderWithQuery(<SectorIndustryTreemap data={DATA} />);
    expect(getByTestId("echart")).toBeTruthy();
  });

  it("renders without crash in market_cap mode", () => {
    const { getByTestId } = renderWithQuery(
      <SectorIndustryTreemap data={DATA} metric="market_cap" />,
    );
    expect(getByTestId("echart")).toBeTruthy();
  });

  it("calls onSectorClick with sector name when sector cell clicked (depth 0)", () => {
    const onSectorClick = vi.fn();
    const { getByTestId } = renderWithQuery(
      <SectorIndustryTreemap data={DATA} onSectorClick={onSectorClick} />,
    );
    getByTestId("echart").click();
    expect(onSectorClick).toHaveBeenCalledWith("Healthcare");
  });
});
