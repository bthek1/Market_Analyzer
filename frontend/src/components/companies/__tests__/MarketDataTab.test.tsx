import { describe, it, expect, vi } from "vitest";
import { buildShortInterestOption } from "@/components/companies/MarketDataTab.chartOptions";
import type { ShortInterest } from "@/types/companies";

vi.mock("echarts-for-react", () => ({
  default: () => null,
}));

const makeSI = (date: string, pct: number, shares: number): ShortInterest => ({
  id: `si-${date}`,
  company: 1,
  fetched_at: "2026-05-28T10:00:00Z",
  date_short_interest: date,
  shares_short: shares,
  shares_short_prior_month: null,
  short_ratio: 1.5,
  short_pct_of_float: pct,
  shares_pct_shares_out: pct,
});

const RECORDS: ShortInterest[] = [
  makeSI("2026-04-15", 0.0060, 95000000),
  makeSI("2026-05-15", 0.0067, 103000000),
  makeSI("2026-03-15", 0.0055, 88000000),
];

describe("buildShortInterestOption", () => {
  it("sorts records chronologically on the x axis", () => {
    const option = buildShortInterestOption(RECORDS);
    const xAxis = option.xAxis as { data: string[] };
    expect(xAxis.data[0]).toBe("2026-03-15");
    expect(xAxis.data[2]).toBe("2026-05-15");
  });

  it("returns two y axes (left pct, right shares)", () => {
    const option = buildShortInterestOption(RECORDS);
    const yAxes = option.yAxis as unknown[];
    expect(yAxes).toHaveLength(2);
  });

  it("returns two line series", () => {
    const option = buildShortInterestOption(RECORDS);
    const series = option.series as { type: string }[];
    expect(series).toHaveLength(2);
    series.forEach((s) => expect(s.type).toBe("line"));
  });

  it("pct-of-float series is on yAxisIndex 0", () => {
    const option = buildShortInterestOption(RECORDS);
    const series = option.series as { name: string; yAxisIndex: number }[];
    expect(series.find((s) => s.name === "Short % of Float")!.yAxisIndex).toBe(0);
  });

  it("shares short series is on yAxisIndex 1", () => {
    const option = buildShortInterestOption(RECORDS);
    const series = option.series as { name: string; yAxisIndex: number }[];
    expect(series.find((s) => s.name === "Shares Short")!.yAxisIndex).toBe(1);
  });
});
