import type { EChartsOption } from "echarts";
import type { CompanySnapshot, InstitutionalHolder } from "@/types/companies";

export function buildOwnershipDonutOption(snapshot: CompanySnapshot): EChartsOption | null {
  if (snapshot.held_pct_institutions === null && snapshot.held_pct_insiders === null) return null;
  const inst = snapshot.held_pct_institutions ?? 0;
  const insider = snapshot.held_pct_insiders ?? 0;
  const pub = Math.max(0, 1 - inst - insider);
  return {
    tooltip: { trigger: "item", formatter: "{b}: {d}%" },
    legend: { bottom: 0 },
    series: [
      {
        type: "pie",
        radius: ["40%", "70%"],
        data: [
          { name: "Institutional", value: parseFloat((inst * 100).toFixed(2)) },
          { name: "Insider", value: parseFloat((insider * 100).toFixed(2)) },
          { name: "Public Float", value: parseFloat((pub * 100).toFixed(2)) },
        ],
        label: { formatter: "{b}\n{d}%" },
      },
    ],
  };
}

export function buildTopHoldersOption(holders: InstitutionalHolder[]): EChartsOption {
  const top = [...holders].sort((a, b) => b.pct_out - a.pct_out).slice(0, 10).reverse();
  return {
    tooltip: { trigger: "axis", formatter: (p: unknown) => {
      const params = p as { name: string; value: number }[];
      return `${params[0].name}: ${(params[0].value * 100).toFixed(2)}%`;
    }},
    grid: { left: 160, right: 24, top: 8, bottom: 20 },
    xAxis: {
      type: "value",
      axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(1)}%` },
    },
    yAxis: {
      type: "category",
      data: top.map((h) => h.holder),
      axisLabel: {
        width: 150,
        overflow: "truncate",
        fontSize: 11,
      },
    },
    series: [
      {
        type: "bar",
        data: top.map((h) => h.pct_out),
        color: "#6366f1",
      },
    ],
  };
}
