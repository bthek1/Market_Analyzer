import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { streamRoute } from "@/api/llm";
import { queryKeys } from "@/api/queryKeys";
import type {
  ChainStepState,
  ChainStepStatus,
  RouteClassification,
  RouteLabel,
  RouteRunDetail,
} from "@/types/llm";

const INITIAL_STEPS: ChainStepState[] = [
  { id: "", step_id: "classify", label: "Classify Query", order: 0, status: "pending", output: null, error: null, started_at: null, completed_at: null },
  { id: "", step_id: "research", label: "Gather Data", order: 1, status: "pending", output: null, error: null, started_at: null, completed_at: null },
  { id: "", step_id: "synthesise", label: "Synthesise", order: 2, status: "pending", output: null, error: null, started_at: null, completed_at: null },
  { id: "", step_id: "format", label: "Format Report", order: 3, status: "pending", output: null, error: null, started_at: null, completed_at: null },
];

// Route-level events carry an "event" key; chain step events do not.
interface ClassifiedEvent {
  event: "classified";
  route: RouteLabel;
  reason: string;
  tickers: string[];
  complexity: RouteClassification["complexity"];
}

interface ResultEvent {
  event: "result";
  route: RouteLabel;
  output: string;
  run_id: string;
}

interface ErrorEvent {
  event: "error";
  error: string;
}

interface ChainStepEvent {
  run_id: string;
  step_id: string;
  label: string;
  status: string;
  output: string | null;
  error: string | null;
}

type RouteEvent = ClassifiedEvent | ResultEvent | ErrorEvent | ChainStepEvent;

export interface UseRoutingReturn {
  classification: RouteClassification | null;
  route: RouteLabel | null;
  isClassifying: boolean;
  isExecuting: boolean;
  chainSteps: ChainStepState[];
  output: string | null;
  error: string | null;
  runId: string | null;
  run: (query: string, model?: string) => void;
  reset: () => void;
  loadFromDetail: (detail: RouteRunDetail) => void;
}

export function useRouting(): UseRoutingReturn {
  const queryClient = useQueryClient();
  const [classification, setClassification] = useState<RouteClassification | null>(null);
  const [route, setRoute] = useState<RouteLabel | null>(null);
  const [isClassifying, setIsClassifying] = useState(false);
  const [isExecuting, setIsExecuting] = useState(false);
  const [chainSteps, setChainSteps] = useState<ChainStepState[]>(INITIAL_STEPS);
  const [output, setOutput] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setClassification(null);
    setRoute(null);
    setIsClassifying(false);
    setIsExecuting(false);
    setChainSteps(INITIAL_STEPS);
    setOutput(null);
    setError(null);
    setRunId(null);
  }, []);

  // History replay: RouteRun persists only the route + final output (not the
  // classifier's tickers/complexity, nor the linked chain steps), so we restore
  // the final answer and route label and leave the decision card hidden.
  const loadFromDetail = useCallback((detail: RouteRunDetail) => {
    abortRef.current?.abort();
    setClassification(null);
    setRoute(detail.route);
    setIsClassifying(false);
    setIsExecuting(false);
    setChainSteps(INITIAL_STEPS);
    setOutput(detail.output || null);
    setError(detail.error || null);
    setRunId(detail.id);
  }, []);

  const run = useCallback(
    (query: string, model?: string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setClassification(null);
      setRoute(null);
      setChainSteps(INITIAL_STEPS);
      setOutput(null);
      setError(null);
      setRunId(null);
      setIsClassifying(true);
      setIsExecuting(false);

      function handleEvent(event: RouteEvent) {
        if ("event" in event) {
          if (event.event === "classified") {
            setClassification({
              route: event.route,
              reason: event.reason,
              tickers: event.tickers,
              complexity: event.complexity,
            });
            setRoute(event.route);
            setIsClassifying(false);
            setIsExecuting(true);
          } else if (event.event === "result") {
            setOutput(event.output);
            setRunId(event.run_id);
            setIsExecuting(false);
            queryClient.invalidateQueries({ queryKey: queryKeys.llm.routeRuns() });
          } else if (event.event === "error") {
            setError(event.error);
            setIsClassifying(false);
            setIsExecuting(false);
          }
          return;
        }

        // chain step event (deep_research path)
        if (event.step_id === "__init__" || event.step_id === "__done__") return;
        setChainSteps((prev) =>
          prev.map((s) =>
            s.step_id === event.step_id
              ? {
                  ...s,
                  status: event.status as ChainStepStatus,
                  output: event.output,
                  error: event.error,
                }
              : s,
          ),
        );
      }

      (async () => {
        try {
          const response = await streamRoute({ query, model: model || null }, controller.signal);
          if (!response.body) {
            setIsClassifying(false);
            setIsExecuting(false);
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
                handleEvent(JSON.parse(raw) as RouteEvent);
              } catch {
                // malformed line - skip
              }
            }
          }
        } catch (err: unknown) {
          if (err instanceof Error && err.name !== "AbortError") {
            setError(err.message);
            setIsClassifying(false);
            setIsExecuting(false);
          }
        }
      })();
    },
    [queryClient],
  );

  return {
    classification,
    route,
    isClassifying,
    isExecuting,
    chainSteps,
    output,
    error,
    runId,
    run,
    reset,
    loadFromDetail,
  };
}
