import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { streamEvaluate } from "@/api/llm";
import { queryKeys } from "@/api/queryKeys";
import type {
  EvalOptIterationState,
  EvalOptRunDetail,
} from "@/types/llm";
import { useLLMSettings } from "./useLLMSettings";

// Evaluator-Optimizer events all carry an "event" key.
interface StartedEvent {
  event: "started";
  max_iterations: number;
  threshold: number;
}

interface DraftEvent {
  event: "draft";
  draft: string;
}

// The step payload IS the row's detail representation (backend `_events.step_event`),
// so the live stream and a refresh-restore produce identical state. Only the `event`
// discriminator is extra.
type IterationEvent = { event: "iteration" } & EvalOptIterationState;

interface ResultEvent {
  event: "result";
  output: string;
  iterations: number;
  best_score: number;
  run_id: string;
}

interface ErrorEvent {
  event: "error";
  error: string;
}

type EvalOptEvent =
  | StartedEvent
  | DraftEvent
  | IterationEvent
  | ResultEvent
  | ErrorEvent;

export interface UseEvaluateReturn {
  draft: string | null;
  iterations: EvalOptIterationState[];
  maxIterations: number;
  threshold: number;
  output: string | null;
  bestScore: number | null;
  isRunning: boolean;
  error: string | null;
  runId: string | null;
  run: (
    query: string,
    model?: string,
    opts?: { maxIterations?: number; threshold?: number },
  ) => void;
  reset: () => void;
  loadFromDetail: (detail: EvalOptRunDetail) => void;
}

function iterationFromEvent({ event: _event, ...step }: IterationEvent): EvalOptIterationState {
  return step;
}

export function useEvaluate(): UseEvaluateReturn {
  const queryClient = useQueryClient();
  const { data: llmSettings } = useLLMSettings();
  const [draft, setDraft] = useState<string | null>(null);
  const [iterations, setIterations] = useState<EvalOptIterationState[]>([]);
  // Show the run's own caps once one is loaded/active; when idle, mirror the live
  // LLM settings so edits in the Settings drawer are reflected immediately.
  const [runMaxIterations, setRunMaxIterations] = useState<number | null>(null);
  const [runThreshold, setRunThreshold] = useState<number | null>(null);
  const maxIterations =
    runMaxIterations ?? llmSettings?.eval_max_iterations ?? 3;
  const threshold = runThreshold ?? llmSettings?.eval_threshold ?? 8;
  const [output, setOutput] = useState<string | null>(null);
  const [bestScore, setBestScore] = useState<number | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setDraft(null);
    setIterations([]);
    setOutput(null);
    setBestScore(null);
    setIsRunning(false);
    setError(null);
    setRunId(null);
    setRunMaxIterations(null);
    setRunThreshold(null);
  }, []);

  const loadFromDetail = useCallback((detail: EvalOptRunDetail) => {
    abortRef.current?.abort();
    // The detail has no standalone draft column; the first iteration's draft is
    // the initial draft.
    setDraft(detail.iterations[0]?.draft ?? null);
    setIterations(detail.iterations);
    setRunMaxIterations(detail.max_iterations);
    setRunThreshold(detail.threshold);
    setOutput(detail.output || null);
    setBestScore(detail.best_score);
    setError(detail.error || null);
    setRunId(detail.id);
    setIsRunning(false);
  }, []);

  const run = useCallback(
    (
      query: string,
      model?: string,
      opts?: { maxIterations?: number; threshold?: number },
    ) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setDraft(null);
      setIterations([]);
      setOutput(null);
      setBestScore(null);
      setError(null);
      setRunId(null);
      setIsRunning(true);

      function handleEvent(event: EvalOptEvent) {
        if (event.event === "started") {
          setRunMaxIterations(event.max_iterations);
          setRunThreshold(event.threshold);
          setDraft(null);
          setIterations([]);
        } else if (event.event === "draft") {
          setDraft(event.draft);
        } else if (event.event === "iteration") {
          // Iterations stream in sequentially - append each as it arrives.
          setIterations((prev) => [...prev, iterationFromEvent(event)]);
        } else if (event.event === "result") {
          setOutput(event.output);
          setBestScore(event.best_score);
          setRunId(event.run_id);
          setIsRunning(false);
          queryClient.invalidateQueries({
            queryKey: queryKeys.llm.evalOptRuns(),
          });
        } else if (event.event === "error") {
          setError(event.error);
          setIsRunning(false);
        }
      }

      (async () => {
        try {
          const response = await streamEvaluate(
            {
              query,
              model: model || null,
              max_iterations: opts?.maxIterations,
              threshold: opts?.threshold,
            },
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
                handleEvent(JSON.parse(raw) as EvalOptEvent);
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
    draft,
    iterations,
    maxIterations,
    threshold,
    output,
    bestScore,
    isRunning,
    error,
    runId,
    run,
    reset,
    loadFromDetail,
  };
}
