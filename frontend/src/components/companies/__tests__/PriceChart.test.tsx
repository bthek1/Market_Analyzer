import React from "react";
import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";
import { PriceChart } from "@/components/companies/PriceChart";
import { buildCandlestickOption } from "@/components/companies/PriceChart.chartOptions";
import type { PriceBar } from "@/types/companies";

vi.mock("echarts-for-react", () => ({
  default: ({ style }: { style?: React.CSSProperties }) => (
    <div data-testid="echart" data-height={style?.height} />
  ),
}));

const makeBar = (date: string, o: string, h: string, l: string, c: string): PriceBar => ({
  id: 1,
  company: 1,
  date,
  open: o,
  high: h,
  low: l,
  close: c,
  volume: 1000000,
});

const BARS: PriceBar[] = [
  makeBar("2024-01-02", "150.00", "155.00", "149.00", "153.00"),
  makeBar("2024-01-03", "153.00", "157.00", "152.00", "156.00"),
  makeBar("2024-01-04", "156.00", "158.00", "154.00", "155.00"),
];

describe("buildCandlestickOption", () => {
  it("maps x axis[0] to bar dates", () => {
    const option = buildCandlestickOption(BARS, 0);
    const xAxes = option.xAxis as { data: string[] }[];
    expect(xAxes[0].data).toEqual(["2024-01-02", "2024-01-03", "2024-01-04"]);
  });

  it("includes a volume bar series as series[1]", () => {
    const option = buildCandlestickOption(BARS, 0);
    const series = option.series as { type: string; data: number[] }[];
    expect(series[1].type).toBe("bar");
    expect(series[1].data).toEqual([1000000, 1000000, 1000000]);
  });

  it("dataZoom xAxisIndex covers both axes", () => {
    const option = buildCandlestickOption(BARS, 0);
    const zooms = option.dataZoom as { xAxisIndex: number[] }[];
    expect(zooms[0].xAxisIndex).toEqual([0, 1]);
  });

  it("maps candlestick series data to [open, close, low, high]", () => {
    const option = buildCandlestickOption(BARS, 0);
    const series = (option.series as { data: number[][] }[])[0];
    expect(series.data[0]).toEqual([150, 153, 149, 155]);
  });

  it("sets dataZoom start to provided value", () => {
    const option = buildCandlestickOption(BARS, 75);
    const zooms = option.dataZoom as { start: number }[];
    expect(zooms[0].start).toBe(75);
    expect(zooms[1].start).toBe(75);
  });

  it("sets candlestick series type", () => {
    const option = buildCandlestickOption(BARS, 0);
    const series = (option.series as { type: string }[])[0];
    expect(series.type).toBe("candlestick");
  });

  it("adds markLine when fiftyDayAverage is provided", () => {
    const option = buildCandlestickOption(BARS, 0, 150);
    const series = (option.series as { markLine?: { data: { yAxis: number; name: string }[] } }[])[0];
    expect(series.markLine).toBeDefined();
    expect(series.markLine!.data[0].yAxis).toBe(150);
    expect(series.markLine!.data[0].name).toBe("50-Day MA");
  });

  it("adds markLine when twoHundredDayAverage is provided", () => {
    const option = buildCandlestickOption(BARS, 0, undefined, 140);
    const series = (option.series as { markLine?: { data: { yAxis: number; name: string }[] } }[])[0];
    expect(series.markLine!.data[0].yAxis).toBe(140);
    expect(series.markLine!.data[0].name).toBe("200-Day MA");
  });

  it("adds both markLines when both averages provided", () => {
    const option = buildCandlestickOption(BARS, 0, 150, 140);
    const series = (option.series as { markLine?: { data: { yAxis: number }[] } }[])[0];
    expect(series.markLine!.data).toHaveLength(2);
  });

  it("has no markLine when no averages provided", () => {
    const option = buildCandlestickOption(BARS, 0);
    const series = (option.series as { markLine?: unknown }[])[0];
    expect(series.markLine).toBeUndefined();
  });
});

describe("PriceChart", () => {
  it("renders nothing when fewer than 2 bars", () => {
    const { container } = renderWithQuery(<PriceChart bars={[BARS[0]]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders the chart when bars are provided", () => {
    renderWithQuery(<PriceChart bars={BARS} />);
    expect(screen.getByTestId("echart")).toBeTruthy();
  });

  it("renders range buttons", () => {
    renderWithQuery(<PriceChart bars={BARS} />);
    expect(screen.getByText("1M")).toBeTruthy();
    expect(screen.getByText("3M")).toBeTruthy();
    expect(screen.getByText("1Y")).toBeTruthy();
    expect(screen.getByText("All")).toBeTruthy();
  });

  it("renders chart with height 480", () => {
    renderWithQuery(<PriceChart bars={BARS} />);
    expect(screen.getByTestId("echart")).toHaveAttribute("data-height", "480");
  });
});
