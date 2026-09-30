import { useEffect, useRef, useState } from "react";
import { ChevronRight, Wrench } from "lucide-react";
import { cn } from "@/lib/utils";
import type { TranscriptTurn } from "@/hooks/useChatAgent";
import type { ChatStepState } from "@/types/chat";

/**
 * The tool calls a turn made, collapsed. A step here is one tool call - the answer step
 * carries no tool and is not worth a row of its own.
 */
function ToolCalls({ steps }: { steps: ChatStepState[] }) {
  const [open, setOpen] = useState(false);
  const calls = steps.filter((s) => s.tool);
  if (calls.length === 0) return null;

  return (
    <div className="mb-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
      >
        <ChevronRight
          className={cn("h-3 w-3 transition-transform", open && "rotate-90")}
        />
        <Wrench className="h-3 w-3" />
        {calls.length === 1 ? "used 1 tool" : `used ${calls.length} tools`}
      </button>

      {open && (
        <div className="mt-1 flex flex-col gap-1.5 border-l pl-3">
          {calls.map((step) => (
            <div key={step.id} className="text-[11px]">
              <div className="font-mono text-foreground">
                {step.tool}({JSON.stringify(step.tool_args ?? {})})
              </div>
              {step.thought && (
                <div className="text-muted-foreground">{step.thought}</div>
              )}
              {step.observation && (
                <pre className="mt-0.5 max-h-32 overflow-auto rounded bg-muted/60 p-1.5 text-[10px] whitespace-pre-wrap break-all">
                  {step.observation}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Bubble({ role, children }: { role: "user" | "assistant"; children: React.ReactNode }) {
  return (
    <div className={cn("flex", role === "user" ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[75%] rounded-2xl px-4 py-2.5 text-sm break-words whitespace-pre-wrap",
          role === "user"
            ? "bg-primary text-primary-foreground"
            : "border bg-card text-foreground",
        )}
      >
        {children}
      </div>
    </div>
  );
}

function Typing() {
  return (
    <span className="inline-flex gap-1" aria-label="Thinking">
      <span className="animate-bounce">.</span>
      <span className="animate-bounce [animation-delay:0.15s]">.</span>
      <span className="animate-bounce [animation-delay:0.3s]">.</span>
    </span>
  );
}

export function Transcript({
  turns,
  summary,
  isRunning,
}: {
  turns: TranscriptTurn[];
  summary: string;
  isRunning: boolean;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  if (turns.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center rounded-lg border bg-muted/20 p-4">
        <p className="text-sm text-muted-foreground">
          Ask about a company, a sector, or anything else — Enter to send.
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto rounded-lg border bg-muted/20 p-4">
      <div className="flex flex-col gap-3">
        {/* Compaction is a property of the CONVERSATION, so it is shown once, at the top,
            rather than against the turn that happened to trigger it. */}
        {summary && (
          <details className="rounded-md border border-dashed bg-background/60 px-3 py-2 text-xs">
            <summary className="cursor-pointer text-muted-foreground">
              Earlier messages summarised
            </summary>
            <p className="mt-2 whitespace-pre-wrap text-muted-foreground">{summary}</p>
          </details>
        )}

        {turns.map((turn, i) => (
          <div key={turn.id ?? `pending-${i}`} className="flex flex-col gap-2">
            <Bubble role="user">{turn.query}</Bubble>

            <div className="flex justify-start">
              <div className="max-w-[75%]">
                <ToolCalls steps={turn.steps} />
                <Bubble role="assistant">
                  {turn.output ? (
                    <>
                      {turn.output}
                      {/* A partial reply must say it is partial. Without this a stopped
                          turn reads as a complete answer that simply ended oddly. */}
                      {turn.status === "stopped" && (
                        <span className="text-muted-foreground italic"> — stopped</span>
                      )}
                    </>
                  ) : turn.error ? (
                    <span className="text-destructive">{turn.error}</span>
                  ) : turn.status === "stopped" ? (
                    <span className="text-muted-foreground italic">Stopped.</span>
                  ) : isRunning && i === turns.length - 1 ? (
                    <Typing />
                  ) : (
                    <span className="text-muted-foreground italic">No reply.</span>
                  )}
                </Bubble>
              </div>
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
