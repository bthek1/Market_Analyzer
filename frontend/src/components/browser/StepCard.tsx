import { Badge } from "@/components/ui/badge";
import { Screenshot } from "./Screenshot";
import type { BrowserStepState } from "@/types/browser";

interface StepCardProps {
  step: BrowserStepState;
  runId: string | null;
  onZoom: (step: BrowserStepState) => void;
}

/** One browser action: what it did, where, what it made of the previous step. */
export function StepCard({ step, runId, onZoom }: StepCardProps) {
  return (
    <li className="flex gap-3 rounded-lg border bg-card p-3">
      <span className="w-6 shrink-0 text-right text-xs text-muted-foreground">
        {step.order + 1}
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary" className="font-mono">
            {step.action || "step"}
          </Badge>
          {step.title && (
            <span className="truncate text-sm font-medium">{step.title}</span>
          )}
          {step.status === "error" && (
            <Badge variant="destructive">failed</Badge>
          )}
        </div>

        {step.url && (
          <a
            href={step.url}
            target="_blank"
            rel="noreferrer noopener"
            className="mt-0.5 block truncate text-xs text-muted-foreground underline-offset-2 hover:underline"
          >
            {step.url}
          </a>
        )}
        {step.output && <p className="mt-1 text-sm">{step.output}</p>}
        {step.evaluation && (
          <p className="mt-1 text-xs text-muted-foreground">{step.evaluation}</p>
        )}
        {step.error && (
          <p className="mt-1 text-xs text-destructive">{step.error}</p>
        )}
      </div>

      {step.screenshot && (
        <Screenshot
          runId={runId}
          order={step.order}
          alt={`Screenshot of step ${step.order + 1}`}
          onClick={() => onZoom(step)}
        />
      )}
    </li>
  );
}
