import type { EChartsOption } from "echarts";
import type { ChartNode, MarketHierarchyMetric } from "@/types/companies";
import { SECTOR_COLORS } from "./SectorIndustrySunburst.chartOptions";

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

function leafLabel(params: unknown, metric: MarketHierarchyMetric): string {
  const p = params as { data: ChartNode };
  if (metric === "market_cap" && p.data.market_cap != null) {
    return `${p.data.name}\n${formatMC(p.data.market_cap)}`;
  }
  return `${p.data.name}\n${p.data.company_count}`;
}

function sectorLabel(params: unknown, metric: MarketHierarchyMetric): string {
  const p = params as { data: ChartNode };
  if (metric === "market_cap" && p.data.market_cap != null) {
    return `${p.data.name}  ·  ${formatMC(p.data.market_cap)}`;
  }
  return `${p.data.name}  ·  ${p.data.company_count}`;
}

export function buildTreemapOption(
  data: ChartNode[],
  metric: MarketHierarchyMetric = "count",
): EChartsOption {
  return {
    color: SECTOR_COLORS,
    animation: true,
    animationDuration: 500,
    animationEasing: "cubicOut",
    tooltip: {
      backgroundColor: "#fff",
      borderColor: "#e5e7eb",
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: "#111" },
      formatter: (params: unknown) => {
        const p = params as { data: ChartNode };
        return tooltipHtml(p.data.name, p.data, metric);
      },
    },
    series: [
      {
        type: "treemap",
        name: "All Sectors",
        data,
        leafDepth: 2,
        roam: false,
        left: 0,
        right: 0,
        top: 32,
        bottom: 0,
        squareRatio: 1,
        label: {
          show: true,
          formatter: (params: unknown) => leafLabel(params, metric),
          fontSize: 11,
          lineHeight: 17,
          color: "#1f2937",
          overflow: "truncate",
        },
        upperLabel: {
          show: true,
          height: 28,
          fontSize: 12,
          fontWeight: "bold",
          formatter: (params: unknown) => sectorLabel(params, metric),
          color: "#1f2937",
          padding: [4, 8],
        },
        itemStyle: {
          borderRadius: 4,
        },
        emphasis: {
          itemStyle: {
            shadowBlur: 10,
            shadowColor: "rgba(0,0,0,0.3)",
          },
          label: {
            fontWeight: "bold",
          },
        },
        levels: [
          {
            upperLabel: { show: false },
          },
          {
            itemStyle: {
              borderWidth: 3,
              gapWidth: 5,
              borderColor: "#f9fafb",
              borderRadius: 6,
            },
            upperLabel: { show: true },
          },
          {
            itemStyle: {
              borderWidth: 1,
              gapWidth: 2,
              borderColor: "rgba(255,255,255,0.6)",
              borderRadius: 3,
            },
            label: { show: true },
          },
        ],
        breadcrumb: {
          show: true,
          height: 20,
          top: 4,
          itemStyle: {
            color: "#f6f7f9",
            borderColor: "#ffffff",
            borderWidth: 1,
            textStyle: {
              color: "#374151",
              fontSize: 10,
            },
          },
          emphasis: {
            itemStyle: {
              color: "#e5e7eb",
            },
          },
        },
      },
    ],
  };
}
