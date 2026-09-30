import type { EChartsOption } from "echarts";
import type { Dividend } from "@/types/companies";

export function buildDividendOption(dividends: Dividend[]): EChartsOption {
  return {
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: dividends.map((d) => d.date) },
    yAxis: { type: "value", name: "Amount ($)" },
    series: [{ type: "bar", data: dividends.map((d) => parseFloat(d.amount)), name: "Dividend" }],
  };
}

export function buildAnnualDividendOption(
  dividends: Dividend[],
  dividendRate?: number | null,
): EChartsOption | null {
  if (dividends.length < 2) return null;

  const byYear = new Map<number, number>();
  for (const d of dividends) {
    const year = parseInt(d.date.slice(0, 4), 10);
    byYear.set(year, (byYear.get(year) ?? 0) + parseFloat(d.amount));
  }
  const years = [...byYear.keys()].sort();
  if (years.length < 2) return null;

  const totals = years.map((y) => parseFloat((byYear.get(y) ?? 0).toFixed(4)));
  const growth = totals.map((v, i) => {
    if (i === 0 || totals[i - 1] === 0) return null;
    return parseFloat(((v - totals[i - 1]) / totals[i - 1] * 100).toFixed(2));
  });

  const markLines =
    dividendRate !== null && dividendRate !== undefined
      ? { data: [{ yAxis: dividendRate, name: "Current Rate", lineStyle: { color: "#f59e0b" }, label: { formatter: `Rate: $${dividendRate.toFixed(2)}` } }], symbol: "none" }
      : undefined;

  return {
    legend: { data: ["Annual Dividend", "YoY Growth %"] },
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: years.map(String) },
    yAxis: [
      { type: "value", name: "Amount ($)" },
      {
        type: "value",
        name: "Growth %",
        axisLabel: { formatter: (v: number) => `${v}%` },
      },
    ],
    series: [
      {
        name: "Annual Dividend",
        type: "bar",
        data: totals,
        markLine: markLines,
        color: "#4ade80",
      },
      {
        name: "YoY Growth %",
        type: "line",
        yAxisIndex: 1,
        data: growth,
        smooth: true,
        color: "#6366f1",
      },
    ],
  };
}
