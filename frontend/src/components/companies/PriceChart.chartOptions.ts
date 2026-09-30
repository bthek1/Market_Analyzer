import type { EChartsOption } from "echarts";
import type { PriceBar } from "@/types/companies";

export function buildCandlestickOption(
  bars: PriceBar[],
  zoomStart: number,
  fiftyDayAverage?: number,
  twoHundredDayAverage?: number,
): EChartsOption {
  const markLines: { yAxis: number; name: string; lineStyle: { color: string } }[] = [];
  if (fiftyDayAverage !== undefined)
    markLines.push({ yAxis: fiftyDayAverage, name: "50-Day MA", lineStyle: { color: "#f59e0b" } });
  if (twoHundredDayAverage !== undefined)
    markLines.push({ yAxis: twoHundredDayAverage, name: "200-Day MA", lineStyle: { color: "#6366f1" } });

  const dates = bars.map((b) => b.date);

  return {
    legend: markLines.length > 0 ? { data: markLines.map((m) => m.name) } : undefined,
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross" },
      formatter: (params: unknown) => {
        const p = params as { axisValue: string; data: number[]; seriesType?: string }[];
        const candle = p.find((item) => item.seriesType === "candlestick");
        if (!candle) return "";
        const [o, c, l, h] = candle.data;
        const vol = p.find((item) => item.seriesType === "bar");
        const volStr = vol
          ? `<br/>Vol: ${((vol.data as unknown as number) / 1e6).toFixed(1)}M`
          : "";
        return `${candle.axisValue}<br/>O: ${o?.toFixed(2)} H: ${h?.toFixed(2)}<br/>L: ${l?.toFixed(2)} C: ${c?.toFixed(2)}${volStr}`;
      },
    },
    grid: [
      { left: 50, right: 16, top: 8, bottom: "32%" },
      { left: 50, right: 16, top: "72%", bottom: 52 },
    ],
    xAxis: [
      {
        type: "category",
        data: dates,
        gridIndex: 0,
        axisLabel: { show: false },
        axisLine: { onZero: false },
        axisTick: { show: false },
      },
      {
        type: "category",
        data: dates,
        gridIndex: 1,
        axisLabel: { fontSize: 10 },
        axisLine: { onZero: false },
      },
    ],
    yAxis: [
      { type: "value", scale: true, gridIndex: 0 },
      {
        type: "value",
        gridIndex: 1,
        splitNumber: 2,
        axisLabel: {
          formatter: (v: number) => `${(v / 1e6).toFixed(0)}M`,
          fontSize: 10,
        },
      },
    ],
    dataZoom: [
      { type: "inside", start: zoomStart, end: 100, xAxisIndex: [0, 1] },
      { type: "slider", start: zoomStart, end: 100, xAxisIndex: [0, 1], bottom: 4, height: 20 },
    ],
    series: [
      {
        type: "candlestick",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: bars.map((b) => [
          parseFloat(b.open),
          parseFloat(b.close),
          parseFloat(b.low),
          parseFloat(b.high),
        ]),
        markLine:
          markLines.length > 0
            ? {
                data: markLines.map((m) => ({
                  yAxis: m.yAxis,
                  name: m.name,
                  lineStyle: m.lineStyle,
                  label: { formatter: m.name, position: "insideEndTop" },
                })),
                symbol: "none",
              }
            : undefined,
      },
      {
        type: "bar",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: bars.map((b) => b.volume),
        itemStyle: { color: "#60a5fa", opacity: 0.7 },
        name: "Volume",
        barMaxWidth: 6,
      },
    ],
  };
}
