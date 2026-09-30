import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { streamChain } from "@/api/llm";
import { queryKeys } from "@/api/queryKeys";
import type {ChainRunDetail, ChainStepState} from "@/types/llm";

const INITIAL_STEPS: ChainStepState[] = [
  { id: "", step_id: "classify", label: "Classify Query", order: 0, status: "pending", output: null, error: null, started_at: null, completed_at: null },
  { id: "", step_id: "research", label: "Gather Data", order: 1, status: "pending", output: null, error: null, started_at: null, completed_at: null },
  { id: "", step_id: "synthesise", label: "Synthesise", order: 2, status: "pending", output: null, error: null, started_at: null, completed_at: null },
  { id: "", step_id: "format", label: "Format Report", order: 3, status: "pending", output: null, error: null, started_at: null, completed_at: null },
];

// A step event IS the row's detail representation (backend `_events.step_payload`) plus
// `run_id`, so the live stream and a refresh-restore produce identical state. The two
// run-level SIGNALS (`__init__` / `__done__`) are not steps and carry only the outer keys.
type SSEEvent = { run_id: string } & (
  | ChainStepState
  | { step_id: "__init__" | "__done__"; label: string; status: string; output: null; error: string | null }
);

export interface UsePromptChainReturn {
  runId: string | null;
  steps: ChainStepState[];
  isRunning: boolean;
  run: (query: string, model?: string) => void;
  reset: () => void;
  loadFromDetail: (detail: ChainRunDetail) => void;
}

export function usePromptChain(): UsePromptChainReturn {
  const queryClient = useQueryClient();
  const [runId, setRunId] = useState<string | null>(null);
  const [steps, setSteps] = useState<ChainStepState[]>(INITIAL_STEPS);
  const [isRunning, setIsRunning] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setRunId(null);
    setSteps(INITIAL_STEPS);
    setIsRunning(false);
  }, []);

  const loadFromDetail = useCallback((detail: ChainRunDetail) => {
    setRunId(detail.id);
    setSteps(detail.steps);
    setIsRunning(false);
  }, []);

  const run = useCallback(
    (query: string, model?: string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setRunId(null);
      setSteps(INITIAL_STEPS);
      setIsRunning(true);

      (async () => {
        try {
          const response = await streamChain(
            { query, model: model || null },
            controller.signal,
          );

          if (!response.body) {
            setIsRunning(false);
            return;
          }

          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() ?? "";

            for (const line of lines) {
              if (!line.startsWith("data: ")) continue;
              const raw = line.slice("data: ".length).trim();
              if (!raw) continue;

              try {
                const event: SSEEvent = JSON.parse(raw);
                handleEvent(event);
              } catch {
                // malformed line — skip
              }
            }
          }
        } catch (err: unknown) {
          if (err instanceof Error && err.name !== "AbortError") {
            setIsRunning(false);
          }
        }
      })();

      function handleEvent(event: SSEEvent) {
        if (event.step_id === "__init__") {
          setRunId(event.run_id);
          return;
        }

        if (event.step_id === "__done__") {
          setIsRunning(false);
          queryClient.invalidateQueries({ queryKey: queryKeys.llm.chainRuns() });
          return;
        }

        // Merge the WHOLE row, not three fields: `id` and the timestamps used to stay at
        // the client-side template's defaults during a live run and only appear after a
        // reload, so the chain card's duration label was missing live.
        const { run_id: _runId, ...step } = event as { run_id: string } & ChainStepState;
        setSteps((prev) =>
          prev.map((s) => (s.step_id === step.step_id ? { ...s, ...step } : s)),
        );
      }
    },
    [queryClient],
  );

  return { runId, steps, isRunning, run, reset, loadFromDetail };
}
