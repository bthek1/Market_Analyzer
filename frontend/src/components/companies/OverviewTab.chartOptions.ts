import type { EChartsOption } from "echarts";
import type { CompanySnapshot } from "@/types/companies";

const RADAR_AXES = [
  { name: "Gross\nMargin", key: "gross_margins" as keyof CompanySnapshot, max: 1.0 },
  { name: "Op\nMargin", key: "operating_margins" as keyof CompanySnapshot, max: 0.5 },
  { name: "Net\nMargin", key: "profit_margins" as keyof CompanySnapshot, max: 0.4 },
  { name: "ROE", key: "return_on_equity" as keyof CompanySnapshot, max: 0.5 },
  { name: "ROA", key: "return_on_assets" as keyof CompanySnapshot, max: 0.25 },
  { name: "Rev\nGrowth", key: "revenue_growth" as keyof CompanySnapshot, max: 0.3 },
] as const;

export function buildRadarOption(s: CompanySnapshot): EChartsOption | null {
  const values = RADAR_AXES.map((ax) => {
    const raw = s[ax.key] as number | null;
    if (raw === null) return null;
    return Math.min(100, Math.max(0, (raw / ax.max) * 100));
  });
  if (values.filter((v) => v !== null).length < 3) return null;
  return {
    radar: {
      indicator: RADAR_AXES.map((ax) => ({ name: ax.name, max: 100 })),
      radius: "65%",
    },
    tooltip: { trigger: "item" },
    series: [
      {
        type: "radar",
        data: [{ value: values.map((v) => v ?? 0), name: "Score" }],
        areaStyle: { opacity: 0.2 },
      },
    ],
  };
}
