import { useState } from "react";
import ReactECharts from "echarts-for-react";
import type { GlobalSyncFreshness, SyncFreshnessBuckets, SyncFreshnessMatrix } from "@/api/companies";
import { useSyncFreshness, useSyncFreshnessMatrix } from "@/hooks/useCompanies";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

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

const C = {
  green:   "#22c55e",
  lime:    "#84cc16",
  yellow:  "#eab308",
  amber:   "#f59e0b",
  orange:  "#f97316",
  red:     "#ef4444",
  crimson: "#dc2626",
  gray:    "#374151",
};

// Color for each of the 7 buckets [lt_1h, h1_6, h6_24, d1_7, d7_30, gt_30d, never]
// Gradient shifts relative to each type's expected cadence — green = fresh, crimson = very overdue.
const TYPE_COLORS: Record<string, string[]> = {
  // Daily (21:30): gradient spreads across all time buckets
  "Prices":         [C.green,  C.lime,   C.yellow, C.orange, C.red,    C.crimson, C.gray],
  "Snapshot":       [C.green,  C.lime,   C.yellow, C.orange, C.red,    C.crimson, C.gray],
  "Short Interest": [C.green,  C.lime,   C.yellow, C.orange, C.red,    C.crimson, C.gray],
  // 2x weekly: healthy window is up to ~3d, so gradient starts at h6_24
  "Dividends":      [C.green,  C.green,  C.lime,   C.yellow, C.orange, C.red,     C.gray],
  // Weekdays (22:00): d1_7 covers weekends — gradient starts at h6_24
  "Options":        [C.green,  C.green,  C.lime,   C.yellow, C.orange, C.red,     C.gray],
  // Weekly: healthy window is up to 7d — gradient starts at d1_7
  "Earnings":       [C.green,  C.green,  C.lime,   C.yellow, C.amber,  C.orange,  C.gray],
  "Profile":        [C.green,  C.green,  C.lime,   C.yellow, C.amber,  C.orange,  C.gray],
  // Monthly: healthy window is up to 30d — gradient starts at d1_7
  "Financials":     [C.green,  C.green,  C.green,  C.lime,   C.yellow, C.amber,   C.gray],
  // Quarterly: healthy window is up to ~90d — gt_30d is still within cycle
  "Institutional":  [C.green,  C.green,  C.green,  C.green,  C.lime,   C.yellow,  C.gray],
};

// Sync frequency label shown in tooltip header
const TYPE_FREQ: Record<string, string> = {
  "Prices":         "daily 21:30",
  "Snapshot":       "daily 22:00",
  "Financials":     "monthly",
  "Dividends":      "2x weekly",
  "Short Interest": "daily",
  "Institutional":  "quarterly",
  "Earnings":       "weekly",
  "Options":        "weekdays 22:00",
  "Profile":        "weekly",
};

function buildOption(data: GlobalSyncFreshness) {
  const labels = [...data.data_types.map((d) => d.label)].reverse();
  const total = data.total_companies || 1;

  const reversedTypes = [...data.data_types].reverse();

  const series = BUCKET_KEYS.map((key, si) => ({
    name: BUCKET_LABELS[key],
    type: "bar" as const,
    stack: "total",
    barMaxWidth: 28,
    itemStyle: {
      color: (params: { dataIndex: number }) => {
        const label = labels[params.dataIndex];
        return (TYPE_COLORS[label] ?? [])[si] ?? C.gray;
      },
    },
    data: reversedTypes.map((dt) => dt.buckets[key]),
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
      fontSize: 10,
      formatter: (params: { dataIndex: number }) => {
        const dt = reversedTypes[params.dataIndex];
        const synced = total - dt.buckets.never;
        const pct = total === 0 ? 0 : Math.round((synced / total) * 100);
        return `${pct}%`;
      },
    },
    data: reversedTypes.map(() => 0),
  };

  return {
    backgroundColor: "transparent",
    legend: { show: false },
    tooltip: {
      trigger: "axis" as const,
      axisPointer: { type: "shadow" as const },
      formatter: (rawParams: unknown) => {
        const params = rawParams as {
          seriesName: string;
          value: number;
          dataIndex: number;
          seriesIndex: number;
        }[];
        if (!params.length) return "";
        const label = labels[params[0].dataIndex];
        const freq = TYPE_FREQ[label] ?? "";
        const rows = params
          .filter((p) => p.seriesName !== "coverage" && p.value > 0)
          .map((p) => {
            const color = (TYPE_COLORS[label] ?? [])[p.seriesIndex] ?? C.gray;
            const pct = ((p.value / total) * 100).toFixed(1);
            return (
              `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;` +
              `background:${color};margin-right:5px"></span>` +
              `${p.seriesName}: <b>${p.value}</b> (${pct}%)`
            );
          })
          .join("<br/>");
        const header = `<b>${label}</b><span style="color:#6b7280;font-size:11px;margin-left:6px">${freq}</span><br/>`;
        return header + (rows || '<span style="color:#6b7280">No data</span>');
      },
    },
    grid: { left: "13%", right: "8%", top: 8, bottom: 8, containLabel: false },
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
      data: labels,
      axisLabel: { color: "#9ca3af", fontSize: 11 },
      axisTick: { show: false },
      axisLine: { show: false },
    },
    series: [...series, coverageSeries],
  };
}

// ---------------------------------------------------------------------------
// Per-company view: one tick per company, alphabetical by symbol
// ---------------------------------------------------------------------------

type Hovered = { label: string; symbol: string; bucket: number; x: number; y: number };

// Mirrors buildOption's grid so both views line up exactly:
// left 13% label gutter, 8% right gutter for the coverage %, 8px top/bottom padding.
const CHART_HEIGHT = 360;

function TickRow({
  label,
  buckets,
  symbols,
  onHover,
  onLeave,
}: {
  label: string;
  buckets: number[];
  symbols: string[];
  onHover: (h: Hovered) => void;
  onLeave: () => void;
}) {
  const colors = TYPE_COLORS[label] ?? [];
  const n = symbols.length || 1;
  const synced = buckets.filter((b) => b !== 6).length;
  const pct = n === 0 ? 0 : Math.round((synced / n) * 100);

  return (
    <div className="flex flex-1 items-center">
      <div className="w-[13%] shrink-0 pr-2 text-right text-[11px] text-[#9ca3af]">{label}</div>
      <svg
        viewBox={`0 0 ${n} 1`}
        preserveAspectRatio="none"
        className="h-7 min-w-0 flex-1"
        shapeRendering="crispEdges"
        onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const i = Math.min(
            n - 1,
            Math.max(0, Math.floor(((e.clientX - rect.left) / rect.width) * n)),
          );
          onHover({
            label,
            symbol: symbols[i],
            bucket: buckets[i] ?? 6,
            x: e.clientX,
            y: rect.top,
          });
        }}
        onMouseLeave={onLeave}
      >
        {buckets.map((b, i) => (
          <rect key={i} x={i} y={0} width={1} height={1} fill={colors[b] ?? C.gray} />
        ))}
      </svg>
      <div className="w-[8%] shrink-0 pl-2 text-[10px] text-[#9ca3af]">{pct}%</div>
    </div>
  );
}

function PerCompanyView({ data }: { data: SyncFreshnessMatrix }) {
  const [hovered, setHovered] = useState<Hovered | null>(null);
  const { symbols } = data;

  return (
    <div className="relative">
      <div className="flex flex-col py-2" style={{ height: CHART_HEIGHT }}>
        {data.data_types.map((dt) => (
          <TickRow
            key={dt.label}
            label={dt.label}
            buckets={dt.buckets}
            symbols={symbols}
            onHover={setHovered}
            onLeave={() => setHovered(null)}
          />
        ))}
      </div>

      {hovered && (
        <div
          className="pointer-events-none fixed z-50 -translate-x-1/2 -translate-y-full rounded border border-border bg-popover px-2 py-1 text-[11px] shadow"
          style={{ left: hovered.x, top: hovered.y - 6 }}
        >
          <b>{hovered.symbol}</b>
          <span className="ml-1 text-muted-foreground">{hovered.label}</span>
          <span className="ml-2">
            <span
              className="mr-1 inline-block h-2 w-2 rounded-full align-middle"
              style={{ background: (TYPE_COLORS[hovered.label] ?? [])[hovered.bucket] ?? C.gray }}
            />
            {BUCKET_LABELS[BUCKET_KEYS[hovered.bucket]]}
          </span>
        </div>
      )}
    </div>
  );
}

function Skeleton() {
  return (
    <div className="animate-pulse space-y-2">
      {Array.from({ length: 10 }).map((_, i) => (
        <div key={i} className="h-6 rounded bg-muted" />
      ))}
    </div>
  );
}

type View = "summary" | "company";

export function SyncFreshnessWidget() {
  const [view, setView] = useState<View>("summary");
  const { data, isLoading } = useSyncFreshness();
  const { data: matrix, isLoading: matrixLoading } = useSyncFreshnessMatrix(view === "company");

  const total = data?.total_companies ?? matrix?.total_companies;

  return (
    <Card className="mb-8">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-4">
          <div>
            <CardTitle className="text-sm font-semibold">Sync Coverage by Data Type</CardTitle>
            <CardDescription className="text-xs">
              {view === "summary" ? (
                <>
                  Each bar = all {total ?? "—"} tracked companies. Green = healthy for that
                  type&apos;s schedule. Red = overdue. Gray = never synced.
                </>
              ) : (
                <>
                  Each tick = one of {total ?? "—"} companies, alphabetical by symbol
                  {matrix && matrix.symbols.length > 0
                    ? ` (${matrix.symbols[0]} to ${matrix.symbols[matrix.symbols.length - 1]})`
                    : ""}
                  . Green = healthy for that type&apos;s schedule. Red = overdue. Gray = never
                  synced.
                </>
              )}
            </CardDescription>
          </div>
          <div className="flex shrink-0 rounded-md border border-border p-0.5 text-[11px]">
            {(["summary", "company"] as View[]).map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => setView(v)}
                className={cn(
                  "rounded px-2 py-1 transition-colors",
                  view === v
                    ? "bg-muted font-medium text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {v === "summary" ? "Percentage" : "Per company"}
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {view === "summary" ? (
          isLoading || !data ? (
            <Skeleton />
          ) : (
            <ReactECharts
              option={buildOption(data)}
              style={{ width: "100%", height: CHART_HEIGHT }}
              notMerge={false}
            />
          )
        ) : matrixLoading || !matrix ? (
          <Skeleton />
        ) : (
          <PerCompanyView data={matrix} />
        )}
      </CardContent>
    </Card>
  );
}
