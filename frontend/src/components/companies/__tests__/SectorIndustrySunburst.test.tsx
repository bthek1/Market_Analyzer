import React from "react";
import { describe, it, expect, vi } from "vitest";
import { renderWithQuery } from "@/test/render";
import { SectorIndustrySunburst } from "@/components/companies/SectorIndustrySunburst";
import { buildSunburstOption } from "@/components/companies/SectorIndustrySunburst.chartOptions";

// Configurable click payload — tests set this before clicking the mock chart.
let mockClickPayload = {
  data: { name: "Technology" },
  treePathInfo: [null, null] as unknown[],
};

vi.mock("echarts-for-react", () => ({
  default: ({ onEvents }: { onEvents?: Record<string, (p: unknown) => void> }) => (
    <div
      data-testid="echart"
      onClick={() => onEvents?.["click"]?.(mockClickPayload)}
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

describe("buildSunburstOption", () => {
  it("returns sunburst series type", () => {
    const option = buildSunburstOption(DATA);
    const series = (option.series as { type: string }[])[0];
    expect(series.type).toBe("sunburst");
  });

  it("passes data through to series", () => {
    const option = buildSunburstOption(DATA);
    const series = (option.series as { data: typeof DATA }[])[0];
    expect(series.data).toBe(DATA);
  });

  it("defines three levels", () => {
    const option = buildSunburstOption(DATA);
    const series = (option.series as { levels: unknown[] }[])[0];
    expect(series.levels).toHaveLength(3);
  });

  it("sector and industry rings both have borderRadius 6", () => {
    const option = buildSunburstOption(DATA);
    const series = (option.series as { levels: { itemStyle?: { borderRadius?: number } }[] }[])[0];
    expect(series.levels[1].itemStyle?.borderRadius).toBe(6);
    expect(series.levels[2].itemStyle?.borderRadius).toBe(6);
  });

  it("tooltip formatter shows company count in count mode", () => {
    const option = buildSunburstOption(DATA, "count");
    const formatter = (option.tooltip as { formatter: (p: unknown) => string }).formatter;
    const html = formatter({ data: DATA[0] });
    expect(html).toContain("15 companies");
    expect(html).not.toContain("$");
  });

  it("tooltip formatter shows market cap in market_cap mode", () => {
    const option = buildSunburstOption(DATA, "market_cap");
    const formatter = (option.tooltip as { formatter: (p: unknown) => string }).formatter;
    const html = formatter({ data: DATA[0] });
    expect(html).toContain("$2.0B");
    expect(html).toContain("15 companies");
  });

  it("renders without crash in market_cap mode", () => {
    const { getByTestId } = renderWithQuery(
      <SectorIndustrySunburst data={DATA} metric="market_cap" />,
    );
    expect(getByTestId("echart")).toBeTruthy();
  });
});

describe("SectorIndustrySunburst", () => {
  it("renders without crash", () => {
    const { getByTestId } = renderWithQuery(<SectorIndustrySunburst data={DATA} />);
    expect(getByTestId("echart")).toBeTruthy();
  });

  it("calls onSectorClick with sector name when sector ring clicked (depth 1)", () => {
    mockClickPayload = {
      data: { name: "Technology" },
      treePathInfo: [null, null],
    };
    const onSectorClick = vi.fn();
    const { getByTestId } = renderWithQuery(
      <SectorIndustrySunburst data={DATA} onSectorClick={onSectorClick} />,
    );
    getByTestId("echart").click();
    expect(onSectorClick).toHaveBeenCalledWith("Technology");
  });

  it("calls onSectorClick with parent sector name when industry ring clicked (depth 2)", () => {
    mockClickPayload = {
      data: { name: "Software" },
      treePathInfo: [null, { name: "Technology" }, null],
    };
    const onSectorClick = vi.fn();
    const { getByTestId } = renderWithQuery(
      <SectorIndustrySunburst data={DATA} onSectorClick={onSectorClick} />,
    );
    getByTestId("echart").click();
    expect(onSectorClick).toHaveBeenCalledWith("Technology");
  });

  it("calls onSectorClick with null when center clicked (depth 0)", () => {
    mockClickPayload = {
      data: { name: "" },
      treePathInfo: [null],
    };
    const onSectorClick = vi.fn();
    const { getByTestId } = renderWithQuery(
      <SectorIndustrySunburst data={DATA} onSectorClick={onSectorClick} />,
    );
    getByTestId("echart").click();
    expect(onSectorClick).toHaveBeenCalledWith(null);
  });
});
