import { useMemo } from "react";
import ReactECharts from "echarts-for-react";
import type { ChartNode, MarketHierarchyMetric } from "@/types/companies";
import { buildSunburstOption } from "./SectorIndustrySunburst.chartOptions";

interface Props {
  data: ChartNode[];
  activeSector?: string | null;
  onSectorClick?: (sectorName: string | null) => void;
  metric?: MarketHierarchyMetric;
}

interface EChartsClickParams {
  data: ChartNode;
  treePathInfo: unknown[];
}

export function SectorIndustrySunburst({ data, onSectorClick, metric = "count" }: Props) {
  const option = useMemo(() => buildSunburstOption(data, metric), [data, metric]);

  function handleClick(params: EChartsClickParams) {
    const path = params.treePathInfo as Array<{ name: string }>;
    const depth = path.length - 1;
    if (depth === 1) onSectorClick?.(params.data.name);
    if (depth === 2) onSectorClick?.(path[1]?.name ?? null);
    if (depth === 0) onSectorClick?.(null);
  }

  return (
    <ReactECharts
      option={option}
      notMerge={false}
      style={{ height: 540 }}
      onEvents={{ click: handleClick }}
    />
  );
}
