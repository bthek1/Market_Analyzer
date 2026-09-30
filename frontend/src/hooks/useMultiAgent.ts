import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { streamMultiAgent } from "@/api/llm";
import { queryKeys } from "@/api/queryKeys";
import type {
  MultiAgentRunDetail,
  MultiAgentStepState,
} from "@/types/llm";
import { useLLMSettings } from "./useLLMSettings";

// Multi-Agent events all carry an "event" key.
interface RouteEvent {
  event: "route";
  agents: string[];
  reason: string | null;
}

// The step payload IS the row's detail representation (backend `_events.step_event`),
// so the live stream and a refresh-restore produce identical state. Only the `event`
// discriminator is extra.
type StepEvent = { event: "step" } & MultiAgentStepState;

interface ResultEvent {
  event: "result";
  output: string;
  agents: number;
  run_id: string;
}

interface ErrorEvent {
  event: "error";
  error: string;
}

type MultiAgentEvent = RouteEvent | StepEvent | ResultEvent | ErrorEvent;

export interface UseMultiAgentReturn {
  agents: string[] | null;
  reason: string | null;
  steps: MultiAgentStepState[];
  maxTools: number;
  output: string | null;
  isRunning: boolean;
  error: string | null;
  runId: string | null;
  run: (query: string, model?: string, opts?: { maxTools?: number }) => void;
  reset: () => void;
  loadFromDetail: (detail: MultiAgentRunDetail) => void;
}

const AGENT_LABELS: Record<string, string> = {
  researcher: "Researcher",
  analyst: "Analyst",
  writer: "Writer",
};

function pendingStep(agentId: string, i: number): MultiAgentStepState {
  return {
    id: "",
    agent_id: agentId,
    label: AGENT_LABELS[agentId] ?? agentId,
    order: i,
    input: null,
    tool_calls: null,
    output: null,
    status: "pending",
    error: null,
  };
}

function stepFromEvent({ event: _event, ...step }: StepEvent): MultiAgentStepState {
  return step;
}

export function useMultiAgent(): UseMultiAgentReturn {
  const queryClient = useQueryClient();
  const { data: llmSettings } = useLLMSettings();
  const [agents, setAgents] = useState<string[] | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [steps, setSteps] = useState<MultiAgentStepState[]>([]);
  const [runMaxTools, setRunMaxTools] = useState<number | null>(null);
  const maxTools = runMaxTools ?? llmSettings?.multiagent_max_tools ?? 4;
  const [output, setOutput] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setAgents(null);
    setReason(null);
    setSteps([]);
    setOutput(null);
    setIsRunning(false);
    setError(null);
    setRunId(null);
    setRunMaxTools(null);
  }, []);

  const loadFromDetail = useCallback((detail: MultiAgentRunDetail) => {
    abortRef.current?.abort();
    setAgents(detail.agents);
    setReason(detail.route_reason || null);
    setSteps(detail.steps);
    setRunMaxTools(detail.max_tools);
    setOutput(detail.output || null);
    setError(detail.error || null);
    setRunId(detail.id);
    setIsRunning(false);
  }, []);

  const run = useCallback(
    (query: string, model?: string, opts?: { maxTools?: number }) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setAgents(null);
      setReason(null);
      setSteps([]);
      setOutput(null);
      setError(null);
      setRunId(null);
      setIsRunning(true);

      function handleEvent(event: MultiAgentEvent) {
        if (event.event === "route") {
          // Seed the pipeline from the roster so the cards render immediately.
          setAgents(event.agents);
          setReason(event.reason);
          setSteps(event.agents.map(pendingStep));
        } else if (event.event === "step") {
          // Upsert this step by order (fall back to agent_id).
          setSteps((prev) => {
            const next = stepFromEvent(event);
            const idx = prev.findIndex(
              (s) => s.order === event.order || s.agent_id === event.agent_id,
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
            queryKey: queryKeys.llm.multiAgentRuns(),
          });
        } else if (event.event === "error") {
          setError(event.error);
          setIsRunning(false);
        }
      }

      (async () => {
        try {
          const response = await streamMultiAgent(
            { query, model: model || null, max_tools: opts?.maxTools },
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
                handleEvent(JSON.parse(raw) as MultiAgentEvent);
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
    agents,
    reason,
    steps,
    maxTools,
    output,
    isRunning,
    error,
    runId,
    run,
    reset,
    loadFromDetail,
  };
}
