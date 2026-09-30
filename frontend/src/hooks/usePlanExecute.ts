import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { streamPlan } from "@/api/llm";
import { queryKeys } from "@/api/queryKeys";
import type {
  PlanExecRunDetail,
  PlanExecStepState,
  PlanStepSpec,
} from "@/types/llm";
import { useLLMSettings } from "./useLLMSettings";

// Plan-and-Execute events all carry an "event" key.
interface StartedEvent {
  event: "started";
  max_steps: number;
  allow_replan: boolean;
}

interface PlanEvent {
  event: "plan";
  steps: PlanStepSpec[];
}

// The step payload IS the row's detail representation (backend `_events.step_event`),
// so the live stream and a refresh-restore produce identical state. Only the `event`
// discriminator is extra.
type StepEvent = { event: "step" } & PlanExecStepState;

interface ReplanEvent {
  event: "replan";
  reason: string;
  steps: PlanStepSpec[];
}

interface ResultEvent {
  event: "result";
  output: string;
  steps: number;
  replans: number;
  run_id: string;
}

interface ErrorEvent {
  event: "error";
  error: string;
}

type PlanExecEvent =
  | StartedEvent
  | PlanEvent
  | StepEvent
  | ReplanEvent
  | ResultEvent
  | ErrorEvent;

export interface UsePlanExecuteReturn {
  plan: PlanStepSpec[] | null;
  steps: PlanExecStepState[];
  maxSteps: number;
  allowReplan: boolean;
  output: string | null;
  replans: number;
  isRunning: boolean;
  error: string | null;
  runId: string | null;
  run: (
    query: string,
    model?: string,
    opts?: { maxSteps?: number; allowReplan?: boolean },
  ) => void;
  reset: () => void;
  loadFromDetail: (detail: PlanExecRunDetail) => void;
}

function stepFromEvent({ event: _event, ...step }: StepEvent): PlanExecStepState {
  return step;
}

export function usePlanExecute(): UsePlanExecuteReturn {
  const queryClient = useQueryClient();
  const { data: llmSettings } = useLLMSettings();
  const [plan, setPlan] = useState<PlanStepSpec[] | null>(null);
  const [steps, setSteps] = useState<PlanExecStepState[]>([]);
  const [runMaxSteps, setRunMaxSteps] = useState<number | null>(null);
  const maxSteps = runMaxSteps ?? llmSettings?.plan_max_steps ?? 6;
  const [allowReplan, setAllowReplan] = useState(true);
  const [output, setOutput] = useState<string | null>(null);
  const [replans, setReplans] = useState(0);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setPlan(null);
    setSteps([]);
    setOutput(null);
    setReplans(0);
    setIsRunning(false);
    setError(null);
    setRunId(null);
    setRunMaxSteps(null);
  }, []);

  const loadFromDetail = useCallback((detail: PlanExecRunDetail) => {
    abortRef.current?.abort();
    setPlan(detail.plan);
    setSteps(detail.steps);
    setRunMaxSteps(detail.max_steps);
    setAllowReplan(detail.allow_replan);
    setReplans(detail.replans);
    setOutput(detail.output || null);
    setError(detail.error || null);
    setRunId(detail.id);
    setIsRunning(false);
  }, []);

  const run = useCallback(
    (
      query: string,
      model?: string,
      opts?: { maxSteps?: number; allowReplan?: boolean },
    ) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setPlan(null);
      setSteps([]);
      setOutput(null);
      setReplans(0);
      setError(null);
      setRunId(null);
      setIsRunning(true);

      function handleEvent(event: PlanExecEvent) {
        if (event.event === "started") {
          setRunMaxSteps(event.max_steps);
          setAllowReplan(event.allow_replan);
          setPlan(null);
          setSteps([]);
        } else if (event.event === "plan") {
          setPlan(event.steps);
        } else if (event.event === "step") {
          // Steps stream in sequentially - append each as it arrives.
          setSteps((prev) => [...prev, stepFromEvent(event)]);
        } else if (event.event === "replan") {
          // The remaining plan was revised - replace it and bump the replan counter.
          setPlan(event.steps);
          setReplans((prev) => prev + 1);
        } else if (event.event === "result") {
          setOutput(event.output);
          setReplans(event.replans);
          setRunId(event.run_id);
          setIsRunning(false);
          queryClient.invalidateQueries({ queryKey: queryKeys.llm.planRuns() });
        } else if (event.event === "error") {
          setError(event.error);
          setIsRunning(false);
        }
      }

      (async () => {
        try {
          const response = await streamPlan(
            {
              query,
              model: model || null,
              max_steps: opts?.maxSteps,
              allow_replan: opts?.allowReplan,
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
                handleEvent(JSON.parse(raw) as PlanExecEvent);
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
    steps,
    maxSteps,
    allowReplan,
    output,
    replans,
    isRunning,
    error,
    runId,
    run,
    reset,
    loadFromDetail,
  };
}
