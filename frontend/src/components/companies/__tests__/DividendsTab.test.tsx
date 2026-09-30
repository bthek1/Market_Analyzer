import { describe, it, expect, vi } from "vitest";
import { buildDividendOption, buildAnnualDividendOption } from "@/components/companies/DividendsTab.chartOptions";
import type { Dividend } from "@/types/companies";

vi.mock("echarts-for-react", () => ({
  default: () => null,
}));

const makeDividend = (date: string, amount: string): Dividend => ({
  id: Math.random(),
  company: 1,
  date,
  amount,
});

const DIVIDENDS: Dividend[] = [
  makeDividend("2023-02-10", "0.2300"),
  makeDividend("2023-05-12", "0.2400"),
  makeDividend("2023-08-11", "0.2400"),
  makeDividend("2023-11-10", "0.2400"),
  makeDividend("2024-02-09", "0.2500"),
  makeDividend("2024-05-10", "0.2500"),
  makeDividend("2024-08-09", "0.2500"),
  makeDividend("2024-11-08", "0.2500"),
];

describe("buildDividendOption", () => {
  it("returns a bar series type", () => {
    const option = buildDividendOption(DIVIDENDS);
    const series = option.series as { type: string }[];
    expect(series[0].type).toBe("bar");
  });

  it("x axis data matches dividend dates in order", () => {
    const option = buildDividendOption(DIVIDENDS);
    const xAxis = option.xAxis as { data: string[] };
    expect(xAxis.data[0]).toBe("2023-02-10");
  });
});

describe("buildAnnualDividendOption", () => {
  it("aggregates dividends by year", () => {
    const option = buildAnnualDividendOption(DIVIDENDS);
    expect(option).not.toBeNull();
    const xAxis = option!.xAxis as { data: string[] };
    expect(xAxis.data).toContain("2023");
    expect(xAxis.data).toContain("2024");
  });

  it("annual bar series has correct 2023 total (~0.95)", () => {
    const option = buildAnnualDividendOption(DIVIDENDS);
    const series = option!.series as { name: string; data: number[] }[];
    const bar = series.find((s) => s.name === "Annual Dividend")!;
    const idx2023 = (option!.xAxis as { data: string[] }).data.indexOf("2023");
    expect(bar.data[idx2023]).toBeCloseTo(0.95, 2);
  });

  it("growth line series is on yAxisIndex 1", () => {
    const option = buildAnnualDividendOption(DIVIDENDS);
    const series = option!.series as { name: string; yAxisIndex: number }[];
    expect(series.find((s) => s.name === "YoY Growth %")!.yAxisIndex).toBe(1);
  });

  it("growth value for first year is null", () => {
    const option = buildAnnualDividendOption(DIVIDENDS);
    const series = option!.series as { data: (number | null)[] }[];
    const growthSeries = series[1];
    expect(growthSeries.data[0]).toBeNull();
  });

  it("returns null when fewer than 2 years of data", () => {
    const single = DIVIDENDS.filter((d) => d.date.startsWith("2023"));
    expect(buildAnnualDividendOption(single)).toBeNull();
  });

  it("adds a markLine when dividendRate is provided", () => {
    const option = buildAnnualDividendOption(DIVIDENDS, 1.0);
    const series = option!.series as { markLine?: { data: unknown[] } }[];
    expect(series[0].markLine?.data).toHaveLength(1);
  });
});
