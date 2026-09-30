import { useState } from "react";
import ReactECharts from "echarts-for-react";
import { Button } from "@/components/ui/button";
import type { PriceBar } from "@/types/companies";
import { buildCandlestickOption } from "./PriceChart.chartOptions";

type RangeKey = "1M" | "3M" | "6M" | "1Y" | "All";

const RANGE_START: Record<RangeKey, number> = {
  All: 0,
  "1Y": 75,
  "6M": 87,
  "3M": 94,
  "1M": 98,
};

export function PriceChart({
  bars,
  fiftyDayAverage,
  twoHundredDayAverage,
}: {
  bars: PriceBar[];
  fiftyDayAverage?: number;
  twoHundredDayAverage?: number;
}) {
  const [range, setRange] = useState<RangeKey>("3M");

  if (bars.length < 2) return null;

  const option = buildCandlestickOption(bars, RANGE_START[range], fiftyDayAverage, twoHundredDayAverage);

  return (
    <div className="space-y-2">
      <div className="flex gap-1">
        {(Object.keys(RANGE_START) as RangeKey[]).reverse().map((r) => (
          <Button
            key={r}
            size="sm"
            variant={range === r ? "default" : "outline"}
            className="px-2 py-1 h-7 text-xs"
            onClick={() => setRange(r)}
          >
            {r}
          </Button>
        ))}
      </div>
      <ReactECharts option={option} style={{ height: 480 }} />
    </div>
  );
}
