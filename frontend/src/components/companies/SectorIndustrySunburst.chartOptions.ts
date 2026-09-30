import type { EChartsOption } from "echarts";
import type { ChartNode, MarketHierarchyMetric } from "@/types/companies";

export const SECTOR_COLORS = [
  "#4E79A7",
  "#F28E2B",
  "#59A14F",
  "#E15759",
  "#76B7B2",
  "#EDC948",
  "#B07AA1",
  "#FF9DA7",
  "#9C755F",
  "#499894",
  "#86BCB6",
  "#BAB0AC",
];

function formatMC(v: number): string {
  if (v >= 1e12) return `$${(v / 1e12).toFixed(1)}T`;
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  return `$${v.toLocaleString()}`;
}

function tooltipHtml(name: string, node: ChartNode, metric: MarketHierarchyMetric): string {
  const countLine = `${node.company_count} ${node.company_count === 1 ? "company" : "companies"}`;
  const valueLine =
    metric === "market_cap" && node.market_cap != null
      ? `<div style="color:#444;font-size:12px">${formatMC(node.market_cap)}</div>`
      : "";
  const secondLine =
    metric === "market_cap"
      ? `${valueLine}<div style="color:#999;font-size:11px">${countLine}</div>`
      : `<div style="color:#666;font-size:12px">${countLine}</div>`;
  return `
    <div style="font-family:system-ui;padding:2px 4px">
      <div style="font-weight:600;font-size:13px;margin-bottom:2px">${name}</div>
      ${secondLine}
    </div>`;
}

export function buildSunburstOption(
  data: ChartNode[],
  metric: MarketHierarchyMetric = "count",
): EChartsOption {
  return {
    color: SECTOR_COLORS,
    animation: true,
    animationDuration: 600,
    animationEasing: "cubicOut",
    tooltip: {
      trigger: "item",
      backgroundColor: "#fff",
      borderColor: "#e5e7eb",
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: "#111" },
      formatter: (params: unknown) => {
        const p = params as { data: ChartNode };
        if (!p.data.name || p.data.name === "undefined") return "";
        return tooltipHtml(p.data.name, p.data, metric);
      },
    },
    series: [
      {
        type: "sunburst",
        data,
        radius: ["0%", "100%"],
        sort: undefined,
        nodeClick: "rootToNode",
        emphasis: {
          focus: "ancestor",
          itemStyle: {
            shadowBlur: 12,
            shadowColor: "rgba(0,0,0,0.25)",
          },
        },
        levels: [
          {
            label: {
              show: true,
              rotate: 0,
              fontSize: 12,
              fontWeight: "bold",
              color: "#ffffff",
              formatter: () => {
                return "" ;
              },
            },
          },
          {
            r0: "40%",
            r: "80%",
            label: {
              rotate: 0,
              fontSize: 12,
              fontWeight: "bold",
              color: "#fff",
              overflow: "truncate",
              width: 80,
              textShadowBlur: 3,
              textShadowColor: "rgba(0,0,0,0.4)",
            },
            itemStyle: { borderWidth: 2, borderColor: "#fff", borderRadius: 6 },
          },
          {
            r0: "80%",
            r: "100%",
            label: {
              rotate: "tangential",
              fontSize: 10,
              color: "#1f2937",
              minAngle: 8,
              overflow: "truncate",
              width: 50,
            },
            itemStyle: { borderWidth: 2, borderColor: "#fff", borderRadius: 6 },
          },
        ],
      },
    ],
  };
}
