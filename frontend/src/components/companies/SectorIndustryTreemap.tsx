import { useMemo } from "react";
import ReactECharts from "echarts-for-react";
import type { ChartNode, MarketHierarchyMetric } from "@/types/companies";
import { buildTreemapOption } from "./SectorIndustryTreemap.chartOptions";

interface Props {
  data: ChartNode[];
  onSectorClick?: (sectorName: string | null) => void;
  metric?: MarketHierarchyMetric;
}

interface EChartsClickParams {
  data: ChartNode;
  treePathInfo: unknown[];
}

export function SectorIndustryTreemap({ data, onSectorClick, metric = "count" }: Props) {
  const option = useMemo(() => buildTreemapOption(data, metric), [data, metric]);

  function handleClick(params: EChartsClickParams) {
    const depth = (params.treePathInfo as unknown[]).length - 1;
    if (depth === 0) onSectorClick?.(params.data.name);
    if (depth < 0) onSectorClick?.(null);
  }

  return (
    <div className="w-full h-[640px]">
      <ReactECharts
        option={option}
        style={{ width: "100%", height: 640 }}
        notMerge={false}
        onEvents={{ click: handleClick }}
      />
    </div>
  );
}
