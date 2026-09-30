import { useState } from "react";
import { useCompanySummary, useCompanySummaryList } from "@/hooks/useCompanySummary";
import { cn } from "@/lib/utils";
import type { CompanySummary, SummaryVerdict } from "@/types/companies";

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

interface AiSummaryTabProps {
  symbol: string;
}

function staleReasons(summary: CompanySummary): string[] {
  const raw = summary.data_snapshot?.stale_data;
  return Array.isArray(raw) ? raw.map(String) : [];
}

function PhraseList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="space-y-1">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      <ul className="list-disc pl-5 space-y-0.5 text-sm">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function SummaryDetail({ summary }: { summary: CompanySummary | undefined }) {
  if (!summary) {
    return (
      <p className="text-sm text-muted-foreground p-4">No AI summary generated yet.</p>
    );
  }

  const stale = staleReasons(summary);
  const drivers = summary.key_drivers ?? [];
  const risks = summary.key_risks ?? [];

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className={cn(
            "inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold tracking-wide",
            VERDICT_STYLES[summary.verdict],
          )}
        >
          {VERDICT_LABELS[summary.verdict]}
        </span>
        {typeof summary.confidence === "number" && (
          <span className="text-xs text-muted-foreground" data-testid="summary-confidence">
            confidence {Math.round(summary.confidence * 100)}%
          </span>
        )}
        <span className="text-xs text-muted-foreground">
          {summary.model_name} &middot; {new Date(summary.generated_at).toLocaleString()}
        </span>
      </div>

      {stale.length > 0 && (
        <div
          className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900"
          data-testid="summary-stale"
        >
          <p className="font-semibold">No verdict: the data is out of date.</p>
          <ul className="list-disc pl-4 mt-1 space-y-0.5">
            {stale.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      )}

      <p className="text-sm leading-relaxed whitespace-pre-wrap">{summary.summary}</p>

      <PhraseList title="Key drivers" items={drivers} />
      <PhraseList title="Key risks" items={risks} />

      {summary.data_snapshot && (
        <details className="rounded-md border bg-muted/30 text-xs">
          <summary className="cursor-pointer px-3 py-2 font-medium">Data used</summary>
          <pre className="overflow-x-auto px-3 pb-3 whitespace-pre-wrap break-words">
            {JSON.stringify(summary.data_snapshot, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

export function AiSummaryTab({ symbol }: AiSummaryTabProps) {
  const { isGenerating, generate } = useCompanySummary(symbol);
  const { summaries, isLoading } = useCompanySummaryList(symbol);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const selected = selectedId !== null
    ? (summaries.find((s) => s.id === selectedId) ?? summaries[0])
    : summaries[0];

  return (
    <div className="mt-4 rounded-lg border bg-card overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center justify-between gap-4 px-4 py-3 border-b">
        <h2 className="text-sm font-semibold">AI Summaries</h2>
        <button
          onClick={() => generate()}
          disabled={isGenerating}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium",
            "transition-colors hover:bg-accent disabled:opacity-50 disabled:cursor-not-allowed",
          )}
        >
          {isGenerating && (
            <span className="h-3 w-3 rounded-full border-2 border-current border-t-transparent animate-spin" />
          )}
          {isGenerating ? "Generating…" : "Generate New Summary"}
        </button>
      </div>

      {/* Body */}
      {isLoading ? (
        <div className="p-4 space-y-2 animate-pulse">
          <div className="h-4 w-32 rounded bg-muted" />
          <div className="h-3 w-full rounded bg-muted" />
          <div className="h-3 w-4/5 rounded bg-muted" />
        </div>
      ) : summaries.length === 0 ? (
        <p className="text-sm text-muted-foreground p-4">No AI summary generated yet.</p>
      ) : (
        <div className="flex min-h-[300px]">
          {/* Left: summary list */}
          <div className="w-56 shrink-0 border-r overflow-y-auto">
            {summaries.map((s) => (
              <button
                key={s.id}
                onClick={() => setSelectedId(s.id)}
                className={cn(
                  "w-full text-left px-3 py-3 border-b last:border-b-0 space-y-1",
                  "hover:bg-accent transition-colors",
                  (selected?.id === s.id) && "bg-accent",
                )}
              >
                <div className="flex items-center gap-1.5">
                  <span
                    className={cn(
                      "inline-flex items-center rounded border px-1.5 py-0 text-[10px] font-semibold tracking-wide leading-5",
                      VERDICT_STYLES[s.verdict],
                    )}
                  >
                    {VERDICT_LABELS[s.verdict]}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground truncate">
                  {new Date(s.generated_at).toLocaleDateString()}
                </p>
                <p className="text-[10px] text-muted-foreground/70 truncate">{s.model_name}</p>
              </button>
            ))}
          </div>

          {/* Right: detail */}
          <div className="flex-1 overflow-y-auto">
            <SummaryDetail summary={selected} />
          </div>
        </div>
      )}
    </div>
  );
}
