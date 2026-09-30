import type { EChartsOption } from "echarts";
import type { ShortInterest } from "@/types/companies";

export function buildShortInterestOption(records: ShortInterest[]): EChartsOption {
  const sorted = [...records].sort((a, b) =>
    (a.date_short_interest ?? "").localeCompare(b.date_short_interest ?? ""),
  );
  const dates = sorted.map((r) => r.date_short_interest ?? "");
  const pctFloat = sorted.map((r) =>
    r.short_pct_of_float !== null
      ? parseFloat((r.short_pct_of_float * 100).toFixed(4))
      : null,
  );
  const sharesShort = sorted.map((r) => r.shares_short);

  return {
    legend: { data: ["Short % of Float", "Shares Short"] },
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: dates },
    yAxis: [
      {
        type: "value",
        name: "% of Float",
        axisLabel: { formatter: (v: number) => `${v.toFixed(2)}%` },
      },
      {
        type: "value",
        name: "Shares Short",
        axisLabel: { formatter: (v: number) => `${(v / 1e6).toFixed(0)}M` },
      },
    ],
    series: [
      {
        name: "Short % of Float",
        type: "line",
        data: pctFloat,
        yAxisIndex: 0,
        smooth: true,
        color: "#ef4444",
      },
      {
        name: "Shares Short",
        type: "line",
        data: sharesShort,
        yAxisIndex: 1,
        smooth: true,
        color: "#6366f1",
      },
    ],
  };
}
