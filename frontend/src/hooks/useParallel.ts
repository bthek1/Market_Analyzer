import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { streamParallel } from "@/api/llm";
import { queryKeys } from "@/api/queryKeys";
import type {
  ParallelRunDetail,
  ParallelStrategy,
  ParallelTaskState,
  VoteVerdict,
} from "@/types/llm";

// Parallel-level events all carry an "event" key.
interface StartedEvent {
  event: "started";
  strategy: ParallelStrategy;
  tasks: { task_id: string; label: string }[];
}

// The task payload IS the row's detail representation (backend `_events.step_event`),
// so the live stream and a refresh-restore produce identical state. Only the `event`
// discriminator is extra.
type TaskEvent = { event: "task" } & ParallelTaskState;

interface ResultEvent {
  event: "result";
  strategy: ParallelStrategy;
  output: string;
  tally: Record<VoteVerdict, number> | null;
  run_id: string;
}

interface ErrorEvent {
  event: "error";
  error: string;
}

type ParallelEvent = StartedEvent | TaskEvent | ResultEvent | ErrorEvent;

export interface UseParallelReturn {
  strategy: ParallelStrategy;
  tasks: ParallelTaskState[];
  tally: Record<VoteVerdict, number> | null;
  output: string | null;
  isRunning: boolean;
  error: string | null;
  runId: string | null;
  run: (query: string, model?: string, opts?: { strategy: ParallelStrategy; n?: number }) => void;
  reset: () => void;
  loadFromDetail: (detail: ParallelRunDetail) => void;
}

export function useParallel(): UseParallelReturn {
  const queryClient = useQueryClient();
  const [strategy, setStrategy] = useState<ParallelStrategy>("sectioning");
  const [tasks, setTasks] = useState<ParallelTaskState[]>([]);
  const [tally, setTally] = useState<Record<VoteVerdict, number> | null>(null);
  const [output, setOutput] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setTasks([]);
    setTally(null);
    setOutput(null);
    setIsRunning(false);
    setError(null);
    setRunId(null);
  }, []);

  const loadFromDetail = useCallback((detail: ParallelRunDetail) => {
    abortRef.current?.abort();
    setStrategy(detail.strategy);
    setTasks(detail.tasks);
    setTally(detail.tally);
    setOutput(detail.output || null);
    setError(detail.error || null);
    setRunId(detail.id);
    setIsRunning(false);
  }, []);

  const run = useCallback(
    (query: string, model?: string, opts?: { strategy: ParallelStrategy; n?: number }) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      const chosen = opts?.strategy ?? "sectioning";
      setStrategy(chosen);
      setTasks([]);
      setTally(null);
      setOutput(null);
      setError(null);
      setRunId(null);
      setIsRunning(true);

      function handleEvent(event: ParallelEvent) {
        if (event.event === "started") {
          setStrategy(event.strategy);
          setTasks(
            event.tasks.map((t, i) => ({
              id: "",
              task_id: t.task_id,
              label: t.label,
              order: i,
              status: "running",
              output: null,
              vote: null,
              error: null,
            })),
          );
        } else if (event.event === "task") {
          setTasks((prev) => {
            const { event: _event, ...task } = event;
            return prev.map((t) => (t.task_id === task.task_id ? task : t));
          });
        } else if (event.event === "result") {
          setOutput(event.output);
          setTally(event.tally);
          setRunId(event.run_id);
          setIsRunning(false);
          queryClient.invalidateQueries({ queryKey: queryKeys.llm.parallelRuns() });
        } else if (event.event === "error") {
          setError(event.error);
          setIsRunning(false);
        }
      }

      (async () => {
        try {
          const response = await streamParallel(
            { query, model: model || null, strategy: chosen, n: opts?.n },
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
                handleEvent(JSON.parse(raw) as ParallelEvent);
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

  return { strategy, tasks, tally, output, isRunning, error, runId, run, reset, loadFromDetail };
}
