import { Markdown } from "@/components/Markdown";
import { Badge } from "@/components/ui/badge";
import type { BrowserStopReason } from "@/types/browser";

const STOP_LABELS: Record<string, string> = {
  complete: "answered",
  budget: "ran out of steps",
  timeout: "ran out of time",
  error: "failed",
};

interface AnswerPanelProps {
  output: string | null;
  sources: string[];
  stopReason: BrowserStopReason;
  error: string | null;
}

export function AnswerPanel({
  output,
  sources,
  stopReason,
  error,
}: AnswerPanelProps) {
  if (!output && !error) return null;

  return (
    <section className="rounded-lg border bg-card p-4">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold">Answer</h2>
        {stopReason && STOP_LABELS[stopReason] && (
          <Badge variant="outline">{STOP_LABELS[stopReason]}</Badge>
        )}
      </div>

      {error ? (
        <p className="mt-2 text-sm text-destructive">{error}</p>
      ) : (
        <div className="prose prose-sm mt-2 max-w-none dark:prose-invert">
          <Markdown>{output ?? ""}</Markdown>
        </div>
      )}

      {sources.length > 0 && (
        <div className="mt-3 border-t pt-3">
          <h3 className="text-xs font-medium text-muted-foreground">Sources</h3>
          <ul className="mt-1 flex flex-col gap-0.5">
            {sources.map((url) => (
              <li key={url}>
                <a
                  href={url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="truncate text-xs text-muted-foreground underline-offset-2 hover:underline"
                >
                  {url}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
