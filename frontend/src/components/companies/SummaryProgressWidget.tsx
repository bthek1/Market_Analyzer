import ReactECharts from "echarts-for-react";
import type { SyncFreshnessBuckets } from "@/api/companies";
import { useSummaryFreshness } from "@/hooks/useCompanies";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type BucketKey = keyof SyncFreshnessBuckets;

const BUCKET_KEYS: BucketKey[] = ["lt_1h", "h1_6", "h6_24", "d1_7", "d7_30", "gt_30d", "never"];

const BUCKET_LABELS: Record<BucketKey, string> = {
  lt_1h: "< 1h",
  h1_6: "1-6h",
  h6_24: "6-24h",
  d1_7: "1-7d",
  d7_30: "7-30d",
  gt_30d: "> 30d",
  never: "Never",
};

// Weekly cadence colours — matches Profile/Earnings gradient in SyncFreshnessChart
const SUMMARY_COLORS = ["#22c55e", "#22c55e", "#84cc16", "#eab308", "#f59e0b", "#f97316", "#374151"];

function buildOption(total: number, buckets: SyncFreshnessBuckets) {
  const generated = total - buckets.never;
  const pct = total === 0 ? 0 : Math.round((generated / total) * 100);

  const series = BUCKET_KEYS.map((key, i) => ({
    name: BUCKET_LABELS[key],
    type: "bar" as const,
    stack: "total",
    barMaxWidth: 28,
    itemStyle: { color: SUMMARY_COLORS[i] },
    data: [buckets[key]],
    emphasis: { focus: "series" as const },
  }));

  const coverageSeries = {
    name: "coverage",
    type: "bar" as const,
    stack: "total",
    silent: true,
    itemStyle: { color: "transparent" },
    label: {
      show: true,
      position: "right" as const,
      color: "#9ca3af",
      fontSize: 11,
      formatter: () => `${generated} / ${total} (${pct}%)`,
    },
    data: [0],
  };

  return {
    backgroundColor: "transparent",
    legend: { show: false },
    tooltip: {
      trigger: "axis" as const,
      axisPointer: { type: "shadow" as const },
      formatter: (rawParams: unknown) => {
        const params = rawParams as { seriesName: string; value: number; seriesIndex: number }[];
        const rows = params
          .filter((p) => p.seriesName !== "coverage" && p.value > 0)
          .map((p) => {
            const color = SUMMARY_COLORS[p.seriesIndex] ?? "#374151";
            const pctVal = ((p.value / (total || 1)) * 100).toFixed(1);
            return (
              `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;` +
              `background:${color};margin-right:5px"></span>` +
              `${p.seriesName}: <b>${p.value}</b> (${pctVal}%)`
            );
          })
          .join("<br/>");
        const header =
          `<b>AI Summaries</b><span style="color:#6b7280;font-size:11px;margin-left:6px">weekly (LLM)</span><br/>`;
        return header + (rows || '<span style="color:#6b7280">No data</span>');
      },
    },
    grid: { left: "12%", right: "18%", top: 8, bottom: 8, containLabel: false },
    xAxis: {
      type: "value" as const,
      max: total,
      axisLabel: { show: false },
      splitLine: { show: false },
      axisTick: { show: false },
      axisLine: { show: false },
    },
    yAxis: {
      type: "category" as const,
      data: ["AI Summaries"],
      axisLabel: { color: "#9ca3af", fontSize: 11 },
      axisTick: { show: false },
      axisLine: { show: false },
    },
    series: [...series, coverageSeries],
  };
}

export function SummaryProgressWidget() {
  const { data, isLoading } = useSummaryFreshness();

  return (
    <Card className="mb-8">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold">AI Summary Generation</CardTitle>
        <CardDescription className="text-xs">
          CompanySummary coverage across all {data?.total_companies ?? "—"} tracked companies.
          Green = generated recently. Gray = never generated.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading || !data ? (
          <div className="animate-pulse h-10 rounded bg-muted" />
        ) : (
          <ReactECharts
            option={buildOption(data.total_companies, data.buckets)}
            style={{ width: "100%", height: 60 }}
            notMerge={false}
          />
        )}
      </CardContent>
    </Card>
  );
}
