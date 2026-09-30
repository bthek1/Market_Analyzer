import type {
  AnalyseRequest,
  AutonomousRunDetail,
  AutonomousRunSummary,
  ComparableAgentType,
  ChatRequest,
  ChatResponse,
  ChainRunDetail,
  ChainRunSummary,
  DagRunDetail,
  DagRunSummary,
  EvalOptRunDetail,
  EvalOptRunSummary,
  OllamaModel,
  MultiAgentRunDetail,
  MultiAgentRunSummary,
  OrchestratorRunDetail,
  OrchestratorRunSummary,
  ParallelRunDetail,
  ParallelRunSummary,
  ParallelStrategy,
  PlanExecRunDetail,
  PlanExecRunSummary,
  ReactRunDetail,
  ReactRunSummary,
  RouteRunDetail,
  RouteRunSummary,
  SummariseRequest,
  LLMSettings,
  LLMSettingsUpdate,
} from "@/types/llm";
import { apiClient } from "./client";

export async function postChat(payload: ChatRequest): Promise<ChatResponse> {
  const { data } = await apiClient.post<ChatResponse>(
    "/api/llm/chat/",
    payload,
  );
  return data;
}

export async function postSummarise(
  payload: SummariseRequest,
): Promise<ChatResponse> {
  const { data } = await apiClient.post<ChatResponse>(
    "/api/llm/summarise/",
    payload,
  );
  return data;
}

export async function postAnalyse(
  payload: AnalyseRequest,
): Promise<ChatResponse> {
  const { data } = await apiClient.post<ChatResponse>(
    "/api/llm/analyse/",
    payload,
  );
  return data;
}

export async function fetchModels(): Promise<OllamaModel[]> {
  const { data } = await apiClient.get<OllamaModel[]>("/api/llm/models/");
  return data;
}

// Cooperatively cancel a running workflow. The backend flips the run's status to
// "stopped"; its background worker then unwinds the generator at the next step.
export async function cancelRun(
  type: HistoryAgentType,
  id: string,
): Promise<{ stopped: boolean }> {
  const { data } = await apiClient.post<{ stopped: boolean }>(
    "/api/llm/runs/stop/",
    {
      type,
      id,
    },
  );
  return data;
}

export function streamChain(
  payload: { query: string; model?: string | null },
  signal?: AbortSignal,
): Promise<Response> {
  const token = localStorage.getItem("access_token");
  return fetch(`${import.meta.env.VITE_API_BASE_URL}/api/llm/chain/run/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  });
}

export async function fetchChainRuns(): Promise<ChainRunSummary[]> {
  const { data } = await apiClient.get<{ results: ChainRunSummary[] }>(
    "/api/llm/chain/",
  );
  return data.results;
}

export async function fetchChainRunDetail(id: string): Promise<ChainRunDetail> {
  const { data } = await apiClient.get<ChainRunDetail>(`/api/llm/chain/${id}/`);
  return data;
}

export function streamRoute(
  payload: { query: string; model?: string | null },
  signal?: AbortSignal,
): Promise<Response> {
  const token = localStorage.getItem("access_token");
  return fetch(`${import.meta.env.VITE_API_BASE_URL}/api/llm/route/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  });
}

export async function fetchRouteRuns(): Promise<RouteRunSummary[]> {
  const { data } = await apiClient.get<{ results: RouteRunSummary[] }>(
    "/api/llm/route/history/",
  );
  return data.results;
}

export async function fetchRouteRunDetail(id: string): Promise<RouteRunDetail> {
  const { data } = await apiClient.get<RouteRunDetail>(`/api/llm/route/${id}/`);
  return data;
}

export function streamParallel(
  payload: {
    query: string;
    model?: string | null;
    strategy: ParallelStrategy;
    n?: number;
  },
  signal?: AbortSignal,
): Promise<Response> {
  const token = localStorage.getItem("access_token");
  return fetch(`${import.meta.env.VITE_API_BASE_URL}/api/llm/parallel/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  });
}

export async function fetchParallelRuns(): Promise<ParallelRunSummary[]> {
  const { data } = await apiClient.get<{ results: ParallelRunSummary[] }>(
    "/api/llm/parallel/history/",
  );
  return data.results;
}

export async function fetchParallelRunDetail(
  id: string,
): Promise<ParallelRunDetail> {
  const { data } = await apiClient.get<ParallelRunDetail>(
    `/api/llm/parallel/${id}/`,
  );
  return data;
}

export function streamReact(
  payload: { query: string; model?: string | null; max_steps?: number },
  signal?: AbortSignal,
): Promise<Response> {
  const token = localStorage.getItem("access_token");
  return fetch(`${import.meta.env.VITE_API_BASE_URL}/api/llm/react/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  });
}

export async function fetchReactRuns(): Promise<ReactRunSummary[]> {
  const { data } = await apiClient.get<{ results: ReactRunSummary[] }>(
    "/api/llm/react/history/",
  );
  return data.results;
}

export async function fetchReactRunDetail(id: string): Promise<ReactRunDetail> {
  const { data } = await apiClient.get<ReactRunDetail>(`/api/llm/react/${id}/`);
  return data;
}

export function streamEvaluate(
  payload: {
    query: string;
    model?: string | null;
    max_iterations?: number;
    threshold?: number;
  },
  signal?: AbortSignal,
): Promise<Response> {
  const token = localStorage.getItem("access_token");
  return fetch(`${import.meta.env.VITE_API_BASE_URL}/api/llm/evaluate/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  });
}

export async function fetchEvalOptRuns(): Promise<EvalOptRunSummary[]> {
  const { data } = await apiClient.get<{ results: EvalOptRunSummary[] }>(
    "/api/llm/evaluate/history/",
  );
  return data.results;
}

export async function fetchEvalOptRunDetail(
  id: string,
): Promise<EvalOptRunDetail> {
  const { data } = await apiClient.get<EvalOptRunDetail>(
    `/api/llm/evaluate/${id}/`,
  );
  return data;
}

export function streamPlan(
  payload: {
    query: string;
    model?: string | null;
    max_steps?: number;
    allow_replan?: boolean;
  },
  signal?: AbortSignal,
): Promise<Response> {
  const token = localStorage.getItem("access_token");
  return fetch(`${import.meta.env.VITE_API_BASE_URL}/api/llm/plan/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  });
}

export async function fetchPlanRuns(): Promise<PlanExecRunSummary[]> {
  const { data } = await apiClient.get<{ results: PlanExecRunSummary[] }>(
    "/api/llm/plan/history/",
  );
  return data.results;
}

export async function fetchPlanRunDetail(
  id: string,
): Promise<PlanExecRunDetail> {
  const { data } = await apiClient.get<PlanExecRunDetail>(
    `/api/llm/plan/${id}/`,
  );
  return data;
}

export function streamOrchestrate(
  payload: {
    query: string;
    model?: string | null;
    max_workers?: number;
  },
  signal?: AbortSignal,
): Promise<Response> {
  const token = localStorage.getItem("access_token");
  return fetch(`${import.meta.env.VITE_API_BASE_URL}/api/llm/orchestrate/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  });
}

export async function fetchOrchestratorRuns(): Promise<
  OrchestratorRunSummary[]
> {
  const { data } = await apiClient.get<{ results: OrchestratorRunSummary[] }>(
    "/api/llm/orchestrate/history/",
  );
  return data.results;
}

export async function fetchOrchestratorRunDetail(
  id: string,
): Promise<OrchestratorRunDetail> {
  const { data } = await apiClient.get<OrchestratorRunDetail>(
    `/api/llm/orchestrate/${id}/`,
  );
  return data;
}

export function streamMultiAgent(
  payload: {
    query: string;
    model?: string | null;
    max_tools?: number;
  },
  signal?: AbortSignal,
): Promise<Response> {
  const token = localStorage.getItem("access_token");
  return fetch(`${import.meta.env.VITE_API_BASE_URL}/api/llm/multiagent/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  });
}

export async function fetchMultiAgentRuns(): Promise<MultiAgentRunSummary[]> {
  const { data } = await apiClient.get<{ results: MultiAgentRunSummary[] }>(
    "/api/llm/multiagent/history/",
  );
  return data.results;
}

export async function fetchMultiAgentRunDetail(
  id: string,
): Promise<MultiAgentRunDetail> {
  const { data } = await apiClient.get<MultiAgentRunDetail>(
    `/api/llm/multiagent/${id}/`,
  );
  return data;
}

export function streamDag(
  payload: {
    query: string;
    model?: string | null;
    max_nodes?: number;
  },
  signal?: AbortSignal,
): Promise<Response> {
  const token = localStorage.getItem("access_token");
  return fetch(`${import.meta.env.VITE_API_BASE_URL}/api/llm/dag/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  });
}

export async function fetchDagRuns(): Promise<DagRunSummary[]> {
  const { data } = await apiClient.get<{ results: DagRunSummary[] }>(
    "/api/llm/dag/history/",
  );
  return data.results;
}

export async function fetchDagRunDetail(id: string): Promise<DagRunDetail> {
  const { data } = await apiClient.get<DagRunDetail>(`/api/llm/dag/${id}/`);
  return data;
}

export function streamAutonomous(
  payload: {
    query: string;
    model?: string | null;
    max_cycles?: number;
    max_subagents?: number;
  },
  signal?: AbortSignal,
): Promise<Response> {
  const token = localStorage.getItem("access_token");
  return fetch(`${import.meta.env.VITE_API_BASE_URL}/api/llm/autonomous/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  });
}

export async function fetchAutonomousRuns(): Promise<AutonomousRunSummary[]> {
  const { data } = await apiClient.get<{ results: AutonomousRunSummary[] }>(
    "/api/llm/autonomous/history/",
  );
  return data.results;
}

export async function fetchAutonomousRunDetail(
  id: string,
): Promise<AutonomousRunDetail> {
  const { data } = await apiClient.get<AutonomousRunDetail>(
    `/api/llm/autonomous/${id}/`,
  );
  return data;
}

export async function fetchLLMSettings(): Promise<LLMSettings> {
  const { data } = await apiClient.get<LLMSettings>("/api/llm/settings/");
  return data;
}

export async function updateLLMSettings(
  payload: LLMSettingsUpdate,
): Promise<LLMSettings> {
  const { data } = await apiClient.put<LLMSettings>(
    "/api/llm/settings/",
    payload,
  );
  return data;
}

// ---------------------------------------------------------------------------
// Unified history — aggregate every persisted workflow's runs into one list.
// "single" has no persistence, so it is excluded.
// ---------------------------------------------------------------------------

export type HistoryAgentType = Exclude<ComparableAgentType, "single">;

export interface HistoryRunSummary {
  id: string;
  type: HistoryAgentType;
  query: string;
  status: "running" | "done" | "error" | "stopped";
  created_at: string;
}

interface BaseRunSummary {
  id: string;
  query: string;
  status: "running" | "done" | "error" | "stopped";
  created_at: string;
}

const HISTORY_SOURCES: {
  type: HistoryAgentType;
  fetch: () => Promise<BaseRunSummary[]>;
}[] = [
  { type: "chain", fetch: fetchChainRuns },
  { type: "route", fetch: fetchRouteRuns },
  { type: "parallel", fetch: fetchParallelRuns },
  { type: "react", fetch: fetchReactRuns },
  { type: "evaluate", fetch: fetchEvalOptRuns },
  { type: "plan", fetch: fetchPlanRuns },
  { type: "orchestrate", fetch: fetchOrchestratorRuns },
  { type: "multiagent", fetch: fetchMultiAgentRuns },
  { type: "dag", fetch: fetchDagRuns },
  { type: "autonomous", fetch: fetchAutonomousRuns },
];

// Fan out to every history endpoint; a failing source is skipped (its runs are
// simply absent) rather than breaking the whole drawer.
export async function fetchAllRuns(): Promise<HistoryRunSummary[]> {
  const settled = await Promise.allSettled(
    HISTORY_SOURCES.map((s) => s.fetch()),
  );
  const rows: HistoryRunSummary[] = [];
  settled.forEach((res, i) => {
    if (res.status !== "fulfilled") return;
    const { type } = HISTORY_SOURCES[i];
    for (const r of res.value) {
      rows.push({
        id: r.id,
        type,
        query: r.query,
        status: r.status,
        created_at: r.created_at,
      });
    }
  });
  rows.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
  return rows;
}
