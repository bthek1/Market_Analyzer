import { useCompanySummary } from "@/hooks/useCompanySummary";
import type { SummaryVerdict } from "@/types/companies";
import { cn } from "@/lib/utils";

const VERDICT_STYLES: Record<SummaryVerdict, string> = {
  buy: "bg-green-100 text-green-800 border-green-200",
  hold: "bg-amber-100 text-amber-800 border-amber-200",
  sell: "bg-red-100 text-red-800 border-red-200",
  insufficient_data: "bg-gray-100 text-gray-600 border-gray-200",
};

const VERDICT_LABELS: Record<SummaryVerdict, string> = {
  buy: "BUY",
  hold: "HOLD",
  sell: "SELL",
  insufficient_data: "INSUFFICIENT DATA",
};

interface SummaryCardProps {
  symbol: string;
}

export function SummaryCard({ symbol }: SummaryCardProps) {
  const { summary, isLoading, notFound } = useCompanySummary(symbol);

  if (isLoading) {
    return (
      <div className="rounded-lg border bg-card p-4 space-y-2 animate-pulse">
        <div className="h-5 w-20 rounded bg-muted" />
        <div className="h-3 w-full rounded bg-muted" />
        <div className="h-3 w-4/5 rounded bg-muted" />
      </div>
    );
  }

  if (notFound || !summary) {
    return (
      <div className="rounded-lg border bg-card p-4 text-sm text-muted-foreground">
        No AI summary available yet.
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <span
          className={cn(
            "inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold tracking-wide",
            VERDICT_STYLES[summary.verdict],
          )}
        >
          {VERDICT_LABELS[summary.verdict]}
        </span>
        <span className="text-xs text-muted-foreground">
          {new Date(summary.generated_at).toLocaleDateString()} · {summary.model_name}
        </span>
      </div>
      <p className="text-sm leading-relaxed whitespace-pre-wrap">{summary.summary}</p>
    </div>
  );
}
