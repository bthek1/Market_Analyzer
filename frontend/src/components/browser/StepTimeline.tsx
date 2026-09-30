import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Screenshot } from "./Screenshot";
import { StepCard } from "./StepCard";
import type { BrowserStepState } from "@/types/browser";

interface StepTimelineProps {
  steps: BrowserStepState[];
  runId: string | null;
  maxSteps: number | null;
  isRunning: boolean;
}

export function StepTimeline({
  steps,
  runId,
  maxSteps,
  isRunning,
}: StepTimelineProps) {
  const [zoomed, setZoomed] = useState<BrowserStepState | null>(null);

  if (!steps.length && !isRunning) return null;

  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <h2 className="text-sm font-semibold text-foreground">Steps</h2>
        <span>
          {steps.length}
          {maxSteps ? ` / ${maxSteps}` : ""}
        </span>
        {isRunning && <Loader2 className="size-3 animate-spin" />}
      </div>

      <ol className="flex flex-col gap-2">
        {steps.map((step) => (
          <StepCard
            key={step.id || step.order}
            step={step}
            runId={runId}
            onZoom={setZoomed}
          />
        ))}
        {isRunning && (
          <li className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
            Thinking about the next action...
          </li>
        )}
      </ol>

      {zoomed && (
        <div
          role="dialog"
          aria-label="Screenshot"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6"
          onClick={() => setZoomed(null)}
        >
          <Screenshot
            runId={runId}
            order={zoomed.order}
            alt={`Screenshot of step ${zoomed.order + 1}`}
            className="max-h-full max-w-full rounded-lg border bg-background object-contain"
          />
        </div>
      )}
    </section>
  );
}
