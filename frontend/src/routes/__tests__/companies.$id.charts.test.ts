import { describe, it, expect } from "vitest";
import { buildRevenueOption } from "@/components/companies/FinancialsTab.chartOptions";
import { buildDividendOption } from "@/components/companies/DividendsTab.chartOptions";
import type { Dividend } from "@/types/companies";

// Pure function tests — no DOM, no mocks needed.

describe("buildRevenueOption", () => {
  const dates = ["2023-12-31", "2022-12-31"];
  const rows = [
    { metric: "Total Revenue", values: [394328000000, 365817000000] },
    { metric: "Net Income", values: [96995000000, 99803000000] },
  ];

  it("sets category x axis with provided dates", () => {
    const option = buildRevenueOption(dates, rows);
    expect((option.xAxis as { data: string[] }).data).toEqual(dates);
  });

  it("maps Total Revenue series data from rows", () => {
    const option = buildRevenueOption(dates, rows);
    const series = option.series as { name: string; data: (number | null)[] }[];
    const rev = series.find((s) => s.name === "Total Revenue")!;
    expect(rev.data).toEqual([394328000000, 365817000000]);
  });

  it("maps Net Income series data from rows", () => {
    const option = buildRevenueOption(dates, rows);
    const series = option.series as { name: string; data: (number | null)[] }[];
    const income = series.find((s) => s.name === "Net Income")!;
    expect(income.data).toEqual([96995000000, 99803000000]);
  });

  it("uses empty array when metric is absent", () => {
    const sparse = [{ metric: "Total Revenue", values: [100, null] }];
    const option = buildRevenueOption(["2023-12-31", "2022-12-31"], sparse);
    const series = option.series as { name: string; data: (number | null)[] }[];
    const income = series.find((s) => s.name === "Net Income")!;
    expect(income.data).toEqual([]);
  });

  it("formats y axis labels as billions", () => {
    const option = buildRevenueOption(dates, rows);
    const yAxis = option.yAxis as { axisLabel: { formatter: (v: number) => string } };
    expect(yAxis.axisLabel.formatter(1_000_000_000)).toBe("$1.0B");
    expect(yAxis.axisLabel.formatter(2_500_000_000)).toBe("$2.5B");
  });
});

describe("buildDividendOption", () => {
  const dividends: Dividend[] = [
    { id: 1, company: 1, date: "2024-03-01", amount: "0.2500" },
    { id: 2, company: 1, date: "2024-06-01", amount: "0.2500" },
    { id: 3, company: 1, date: "2024-09-01", amount: "0.2600" },
  ];

  it("maps x axis to dividend dates", () => {
    const option = buildDividendOption(dividends);
    expect((option.xAxis as { data: string[] }).data).toEqual([
      "2024-03-01",
      "2024-06-01",
      "2024-09-01",
    ]);
  });

  it("parses amount strings to floats for series data", () => {
    const option = buildDividendOption(dividends);
    const series = (option.series as { data: number[] }[])[0];
    expect(series.data).toEqual([0.25, 0.25, 0.26]);
  });

  it("sets bar series type", () => {
    const option = buildDividendOption(dividends);
    const series = (option.series as { type: string }[])[0];
    expect(series.type).toBe("bar");
  });

  it("sets y axis name to Amount ($)", () => {
    const option = buildDividendOption(dividends);
    expect((option.yAxis as { name: string }).name).toBe("Amount ($)");
  });
});
