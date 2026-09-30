import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { streamOrchestrate } from "@/api/llm";
import { queryKeys } from "@/api/queryKeys";
import type {
  OrchestratorRunDetail,
  OrchestratorSubtaskSpec,
  OrchestratorWorkerState,
} from "@/types/llm";
import { useLLMSettings } from "./useLLMSettings";

// Orchestrator-Workers events all carry an "event" key.
interface StartedEvent {
  event: "started";
  max_workers: number;
}

interface PlanEvent {
  event: "plan";
  subtasks: OrchestratorSubtaskSpec[];
}

// The step payload IS the row's detail representation (backend `_events.step_event`),
// so the live stream and a refresh-restore produce identical state. Only the `event`
// discriminator is extra.
type WorkerEvent = { event: "worker" } & OrchestratorWorkerState;

interface ResultEvent {
  event: "result";
  output: string;
  workers: number;
  run_id: string;
}

interface ErrorEvent {
  event: "error";
  error: string;
}

type OrchestratorEvent =
  | StartedEvent
  | PlanEvent
  | WorkerEvent
  | ResultEvent
  | ErrorEvent;

export interface UseOrchestratorReturn {
  plan: OrchestratorSubtaskSpec[] | null;
  workers: OrchestratorWorkerState[];
  maxWorkers: number;
  output: string | null;
  isRunning: boolean;
  error: string | null;
  runId: string | null;
  run: (query: string, model?: string, opts?: { maxWorkers?: number }) => void;
  reset: () => void;
  loadFromDetail: (detail: OrchestratorRunDetail) => void;
}

function workerFromSubtask(
  st: OrchestratorSubtaskSpec,
  i: number,
): OrchestratorWorkerState {
  return {
    id: "",
    worker_id: st.focus,
    label: st.focus,
    task: st.task,
    order: i,
    tool: st.tool,
    tool_args: st.args,
    observation: null,
    output: null,
    status: "pending",
    error: null,
  };
}

function workerFromEvent({ event: _event, ...step }: WorkerEvent): OrchestratorWorkerState {
  return step;
}

export function useOrchestrator(): UseOrchestratorReturn {
  const queryClient = useQueryClient();
  const { data: llmSettings } = useLLMSettings();
  const [plan, setPlan] = useState<OrchestratorSubtaskSpec[] | null>(null);
  const [workers, setWorkers] = useState<OrchestratorWorkerState[]>([]);
  const [runMaxWorkers, setRunMaxWorkers] = useState<number | null>(null);
  const maxWorkers = runMaxWorkers ?? llmSettings?.orch_max_workers ?? 4;
  const [output, setOutput] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setPlan(null);
    setWorkers([]);
    setOutput(null);
    setIsRunning(false);
    setError(null);
    setRunId(null);
    setRunMaxWorkers(null);
  }, []);

  const loadFromDetail = useCallback((detail: OrchestratorRunDetail) => {
    abortRef.current?.abort();
    setPlan(detail.plan);
    setWorkers(detail.workers);
    setRunMaxWorkers(detail.max_workers);
    setOutput(detail.output || null);
    setError(detail.error || null);
    setRunId(detail.id);
    setIsRunning(false);
  }, []);

  const run = useCallback(
    (query: string, model?: string, opts?: { maxWorkers?: number }) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setPlan(null);
      setWorkers([]);
      setOutput(null);
      setError(null);
      setRunId(null);
      setIsRunning(true);

      function handleEvent(event: OrchestratorEvent) {
        if (event.event === "started") {
          setRunMaxWorkers(event.max_workers);
          setPlan(null);
          setWorkers([]);
        } else if (event.event === "plan") {
          // Seed the worker grid from the decomposition so cards render immediately.
          setPlan(event.subtasks);
          setWorkers(event.subtasks.map(workerFromSubtask));
        } else if (event.event === "worker") {
          // Upsert this worker by worker_id (fall back to order).
          setWorkers((prev) => {
            const next = workerFromEvent(event);
            const idx = prev.findIndex(
              (w) => w.worker_id === event.worker_id || w.order === event.order,
            );
            if (idx === -1) return [...prev, next];
            const copy = [...prev];
            copy[idx] = next;
            return copy;
          });
        } else if (event.event === "result") {
          setOutput(event.output);
          setRunId(event.run_id);
          setIsRunning(false);
          queryClient.invalidateQueries({
            queryKey: queryKeys.llm.orchestratorRuns(),
          });
        } else if (event.event === "error") {
          setError(event.error);
          setIsRunning(false);
        }
      }

      (async () => {
        try {
          const response = await streamOrchestrate(
            { query, model: model || null, max_workers: opts?.maxWorkers },
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
                handleEvent(JSON.parse(raw) as OrchestratorEvent);
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
    plan,
    workers,
    maxWorkers,
    output,
    isRunning,
    error,
    runId,
    run,
    reset,
    loadFromDetail,
  };
}
