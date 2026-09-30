import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { streamAutonomous } from "@/api/llm";
import { queryKeys } from "@/api/queryKeys";
import type {
  AutonomousCycleState,
  AutonomousRunDetail,
  AutonomousStopReason,
} from "@/types/llm";
import { useLLMSettings } from "./useLLMSettings";

// Autonomous events all carry an "event" key.
interface GoalEvent {
  event: "goal";
  goal: string;
  backlog: string[];
  max_cycles: number;
}

// The step payload IS the row's detail representation (backend `_events.step_event`),
// so the live stream and a refresh-restore produce identical state. Only the `event`
// discriminator is extra.
type CycleEvent = { event: "cycle" } & AutonomousCycleState;

interface ResultEvent {
  event: "result";
  output: string;
  cycles: number;
  stop_reason: AutonomousStopReason;
  run_id: string;
}

interface ErrorEvent {
  event: "error";
  error: string;
  stop_reason?: AutonomousStopReason;
}

type AutonomousEvent = GoalEvent | CycleEvent | ResultEvent | ErrorEvent;

export interface UseAutonomousReturn {
  goal: string | null;
  backlog: string[];
  cycles: AutonomousCycleState[];
  maxCycles: number;
  stopReason: AutonomousStopReason | null;
  output: string | null;
  isRunning: boolean;
  error: string | null;
  runId: string | null;
  run: (
    query: string,
    model?: string,
    opts?: { maxCycles?: number; maxSubagents?: number },
  ) => void;
  reset: () => void;
  loadFromDetail: (detail: AutonomousRunDetail) => void;
}

function cycleFromEvent({ event: _event, ...step }: CycleEvent): AutonomousCycleState {
  return step;
}

export function useAutonomous(): UseAutonomousReturn {
  const queryClient = useQueryClient();
  const { data: llmSettings } = useLLMSettings();
  const [goal, setGoal] = useState<string | null>(null);
  const [backlog, setBacklog] = useState<string[]>([]);
  const [cycles, setCycles] = useState<AutonomousCycleState[]>([]);
  // Show the run's own cap once one is loaded/active; when idle, mirror the live
  // LLM setting so edits in the Settings drawer are reflected immediately.
  const [runMaxCycles, setRunMaxCycles] = useState<number | null>(null);
  const maxCycles = runMaxCycles ?? llmSettings?.auto_max_cycles ?? 8;
  const [stopReason, setStopReason] = useState<AutonomousStopReason | null>(
    null,
  );
  const [output, setOutput] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setGoal(null);
    setBacklog([]);
    setCycles([]);
    setStopReason(null);
    setOutput(null);
    setIsRunning(false);
    setError(null);
    setRunId(null);
    setRunMaxCycles(null);
  }, []);

  const loadFromDetail = useCallback((detail: AutonomousRunDetail) => {
    abortRef.current?.abort();
    setGoal(detail.goal || null);
    setBacklog(detail.backlog ?? []);
    setCycles(detail.cycles);
    setRunMaxCycles(detail.max_cycles);
    setStopReason(detail.stop_reason || null);
    setOutput(detail.output || null);
    setError(detail.error || null);
    setRunId(detail.id);
    setIsRunning(false);
  }, []);

  const run = useCallback(
    (
      query: string,
      model?: string,
      opts?: { maxCycles?: number; maxSubagents?: number },
    ) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setRunMaxCycles(null);
      setGoal(null);
      setBacklog([]);
      setCycles([]);
      setStopReason(null);
      setOutput(null);
      setError(null);
      setRunId(null);
      setIsRunning(true);

      function handleEvent(event: AutonomousEvent) {
        if (event.event === "goal") {
          setGoal(event.goal);
          setBacklog(event.backlog);
          setRunMaxCycles(event.max_cycles);
        } else if (event.event === "cycle") {
          // The backlog is rewritten each cycle - keep the latest non-null view.
          if (event.backlog) setBacklog(event.backlog);
          setCycles((prev) => {
            const next = cycleFromEvent(event);
            const idx = prev.findIndex((c) => c.index === event.index);
            if (idx === -1) return [...prev, next];
            const copy = [...prev];
            copy[idx] = next;
            return copy;
          });
        } else if (event.event === "result") {
          setOutput(event.output);
          setStopReason(event.stop_reason);
          setRunId(event.run_id);
          setIsRunning(false);
          queryClient.invalidateQueries({
            queryKey: queryKeys.llm.autonomousRuns(),
          });
        } else if (event.event === "error") {
          setError(event.error);
          if (event.stop_reason) setStopReason(event.stop_reason);
          setIsRunning(false);
        }
      }

      (async () => {
        try {
          const response = await streamAutonomous(
            {
              query,
              model: model || null,
              max_cycles: opts?.maxCycles,
              max_subagents: opts?.maxSubagents,
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
                handleEvent(JSON.parse(raw) as AutonomousEvent);
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
    goal,
    backlog,
    cycles,
    maxCycles,
    stopReason,
    output,
    isRunning,
    error,
    runId,
    run,
    reset,
    loadFromDetail,
  };
}
