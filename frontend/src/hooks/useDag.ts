import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { streamDag } from "@/api/llm";
import { queryKeys } from "@/api/queryKeys";
import type {
  DagNodeState,
  DagPlanNode,
  DagRunDetail,
} from "@/types/llm";
import { useLLMSettings } from "./useLLMSettings";

// DAG events all carry an "event" key.
interface PlanEvent {
  event: "plan";
  nodes: DagPlanNode[];
  waves: string[][];
}

interface WaveEvent {
  event: "wave";
  index: number;
  node_ids: string[];
}

// The step payload IS the row's detail representation (backend `_events.step_event`),
// so the live stream and a refresh-restore produce identical state. Only the `event`
// discriminator is extra.
type NodeEvent = { event: "node" } & DagNodeState;

interface ResultEvent {
  event: "result";
  output: string;
  nodes: number;
  waves: number;
  run_id: string;
}

interface ErrorEvent {
  event: "error";
  error: string;
}

type DagEvent = PlanEvent | WaveEvent | NodeEvent | ResultEvent | ErrorEvent;

export interface UseDagReturn {
  nodes: DagNodeState[];
  waves: string[][] | null;
  maxNodes: number;
  output: string | null;
  isRunning: boolean;
  error: string | null;
  runId: string | null;
  run: (query: string, model?: string, opts?: { maxNodes?: number }) => void;
  reset: () => void;
  loadFromDetail: (detail: DagRunDetail) => void;
}

function pendingNode(plan: DagPlanNode, i: number): DagNodeState {
  return {
    id: "",
    node_id: plan.id,
    label: plan.focus,
    task: plan.task,
    wave: plan.wave,
    order: i,
    depends_on: plan.depends_on,
    tool: plan.tool,
    args: plan.args,
    observation: null,
    output: null,
    status: "pending",
    error: null,
  };
}

function nodeFromEvent({ event: _event, ...step }: NodeEvent): DagNodeState {
  return step;
}

export function useDag(): UseDagReturn {
  const queryClient = useQueryClient();
  const { data: llmSettings } = useLLMSettings();
  const [nodes, setNodes] = useState<DagNodeState[]>([]);
  const [waves, setWaves] = useState<string[][] | null>(null);
  const [runMaxNodes, setRunMaxNodes] = useState<number | null>(null);
  const maxNodes = runMaxNodes ?? llmSettings?.dag_max_nodes ?? 6;
  const [output, setOutput] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setNodes([]);
    setWaves(null);
    setOutput(null);
    setIsRunning(false);
    setError(null);
    setRunId(null);
    setRunMaxNodes(null);
  }, []);

  const loadFromDetail = useCallback((detail: DagRunDetail) => {
    abortRef.current?.abort();
    setNodes(detail.nodes);
    setWaves(detail.plan?.waves ?? null);
    setRunMaxNodes(detail.max_nodes);
    setOutput(detail.output || null);
    setError(detail.error || null);
    setRunId(detail.id);
    setIsRunning(false);
  }, []);

  const run = useCallback(
    (query: string, model?: string, opts?: { maxNodes?: number }) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setNodes([]);
      setWaves(null);
      setOutput(null);
      setError(null);
      setRunId(null);
      setIsRunning(true);

      function handleEvent(event: DagEvent) {
        if (event.event === "plan") {
          // Seed the graph from the plan so the whole DAG renders immediately.
          setWaves(event.waves);
          setNodes(event.nodes.map(pendingNode));
        } else if (event.event === "wave") {
          // Flip this wave's nodes to running.
          setNodes((prev) =>
            prev.map((n) =>
              event.node_ids.includes(n.node_id)
                ? { ...n, status: "running" }
                : n,
            ),
          );
        } else if (event.event === "node") {
          // Upsert this node by node_id.
          setNodes((prev) => {
            const next = nodeFromEvent(event);
            const idx = prev.findIndex((n) => n.node_id === event.node_id);
            if (idx === -1) return [...prev, next];
            const copy = [...prev];
            copy[idx] = next;
            return copy;
          });
        } else if (event.event === "result") {
          setOutput(event.output);
          setRunId(event.run_id);
          setIsRunning(false);
          queryClient.invalidateQueries({ queryKey: queryKeys.llm.dagRuns() });
        } else if (event.event === "error") {
          setError(event.error);
          setIsRunning(false);
        }
      }

      (async () => {
        try {
          const response = await streamDag(
            { query, model: model || null, max_nodes: opts?.maxNodes },
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
                handleEvent(JSON.parse(raw) as DagEvent);
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
    nodes,
    waves,
    maxNodes,
    output,
    isRunning,
    error,
    runId,
    run,
    reset,
    loadFromDetail,
  };
}
