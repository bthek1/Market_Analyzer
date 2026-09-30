import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { streamReact } from "@/api/llm";
import { queryKeys } from "@/api/queryKeys";
import type {
  ReactRunDetail,
  ReactStepState,
} from "@/types/llm";
import { useLLMSettings } from "./useLLMSettings";

// React-level events all carry an "event" key.
interface StartedEvent {
  event: "started";
  max_steps: number;
  tools: string[];
}

// The step payload IS the row's detail representation (backend `_events.step_event`),
// so the live stream and a refresh-restore produce identical state. Only the `event`
// discriminator is extra.
type StepEvent = { event: "step" } & ReactStepState;

interface ResultEvent {
  event: "result";
  output: string;
  run_id: string;
}

interface ErrorEvent {
  event: "error";
  error: string;
}

type ReactEvent = StartedEvent | StepEvent | ResultEvent | ErrorEvent;

export interface UseReactReturn {
  steps: ReactStepState[];
  maxSteps: number;
  output: string | null;
  isRunning: boolean;
  error: string | null;
  runId: string | null;
  run: (query: string, model?: string, opts?: { maxSteps?: number }) => void;
  reset: () => void;
  loadFromDetail: (detail: ReactRunDetail) => void;
}

function stepFromEvent({ event: _event, ...step }: StepEvent): ReactStepState {
  return step;
}

export function useReact(): UseReactReturn {
  const queryClient = useQueryClient();
  const { data: llmSettings } = useLLMSettings();
  const [steps, setSteps] = useState<ReactStepState[]>([]);
  const [runMaxSteps, setRunMaxSteps] = useState<number | null>(null);
  const maxSteps = runMaxSteps ?? llmSettings?.react_max_steps ?? 6;
  const [output, setOutput] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setSteps([]);
    setOutput(null);
    setIsRunning(false);
    setError(null);
    setRunId(null);
    setRunMaxSteps(null);
  }, []);

  const loadFromDetail = useCallback((detail: ReactRunDetail) => {
    abortRef.current?.abort();
    setSteps(detail.steps);
    setRunMaxSteps(detail.max_steps);
    setOutput(detail.output || null);
    setError(detail.error || null);
    setRunId(detail.id);
    setIsRunning(false);
  }, []);

  const run = useCallback(
    (query: string, model?: string, opts?: { maxSteps?: number }) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setSteps([]);
      setOutput(null);
      setError(null);
      setRunId(null);
      setIsRunning(true);

      function handleEvent(event: ReactEvent) {
        if (event.event === "started") {
          setRunMaxSteps(event.max_steps);
          setSteps([]);
        } else if (event.event === "step") {
          // ReAct steps stream in sequentially - append each as it arrives.
          setSteps((prev) => [...prev, stepFromEvent(event)]);
        } else if (event.event === "result") {
          setOutput(event.output);
          setRunId(event.run_id);
          setIsRunning(false);
          queryClient.invalidateQueries({
            queryKey: queryKeys.llm.reactRuns(),
          });
        } else if (event.event === "error") {
          setError(event.error);
          setIsRunning(false);
        }
      }

      (async () => {
        try {
          const response = await streamReact(
            { query, model: model || null, max_steps: opts?.maxSteps },
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
                handleEvent(JSON.parse(raw) as ReactEvent);
              } catch {
                // malformed line - skip
              }
            }
          }
        } catch (err: unknown) {
          if (err instanceof Error && err.name !== "AbortError") {
            setError(err.message);
            setIsRunning(false);
          }
        }
      })();
    },
    [queryClient],
  );

  return {
    steps,
    maxSteps,
    output,
    isRunning,
    error,
    runId,
    run,
    reset,
    loadFromDetail,
  };
}
