import type { EChartsOption } from "echarts";
import type { EarningsDate } from "@/types/companies";

export function buildSurpriseTrendOption(records: EarningsDate[]): EChartsOption | null {
  const past = records
    .filter((r) => !r.is_upcoming && r.surprise_pct !== null)
    .slice(0, 8)
    .reverse();
  if (past.length === 0) return null;

  return {
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      valueFormatter: (v: unknown) => `${(v as number).toFixed(2)}%`,
    },
    xAxis: {
      type: "category",
      data: past.map((r) => r.earnings_date),
      axisLabel: { rotate: 30, fontSize: 11 },
    },
    yAxis: {
      type: "value",
      name: "Surprise %",
      axisLabel: { formatter: (v: number) => `${v}%` },
    },
    series: [
      {
        type: "bar",
        data: past.map((r) => ({
          value: r.surprise_pct,
          itemStyle: {
            color: (r.surprise_pct ?? 0) >= 0 ? "#16a34a" : "#ef4444",
          },
        })),
        markLine: {
          data: [{ yAxis: 0 }],
          lineStyle: { color: "#94a3b8", type: "dashed" },
          symbol: "none",
          label: { show: false },
        },
      },
    ],
  };
}

export function buildEPSOption(records: EarningsDate[]): EChartsOption {
  const past = records.filter((r) => !r.is_upcoming && r.reported_eps !== null).slice(0, 8).reverse();
  return {
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { data: ["EPS Estimate", "Reported EPS"] },
    xAxis: { type: "category", data: past.map((r) => r.earnings_date) },
    yAxis: { type: "value", name: "EPS ($)" },
    series: [
      {
        name: "EPS Estimate",
        type: "bar",
        data: past.map((r) => r.eps_estimate),
        color: "#94a3b8",
      },
      {
        name: "Reported EPS",
        type: "bar",
        data: past.map((r) => ({
          value: r.reported_eps,
          itemStyle: {
            color:
              r.reported_eps !== null && r.eps_estimate !== null && r.reported_eps >= r.eps_estimate
                ? "#16a34a"
                : "#ef4444",
          },
        })),
      },
    ],
  };
}
