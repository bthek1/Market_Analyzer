export type MessageRole = "user" | "assistant" | "system";

export interface Message {
  role: MessageRole;
  content: string;
}

export interface ChatRequest {
  messages: Message[];
  model?: string | null;
}

export interface ChatResponse {
  content: string;
}

export interface SummariseRequest {
  text: string;
  model?: string | null;
}

export interface AnalyseRequest {
  text: string;
  context?: string | null;
  model?: string | null;
}

export interface OllamaModel {
  name: string;
  size_gb: number;
}

export type ComparableAgentType =
  | "single"
  | "chain"
  | "route"
  | "parallel"
  | "react"
  | "evaluate"
  | "plan"
  | "orchestrate"
  | "multiagent"
  | "dag"
  | "autonomous";

export type RouteLabel = "simple" | "analysis" | "deep_research";

export type RouteComplexity = "low" | "medium" | "high";

export interface RouteClassification {
  route: RouteLabel;
  reason: string;
  tickers: string[];
  complexity: RouteComplexity;
}

export interface RouteRunSummary {
  id: string;
  query: string;
  route: RouteLabel | null;
  route_reason: string;
  status: "running" | "done" | "error";
  model: string;
  created_at: string;
  completed_at: string | null;
}

export interface RouteRunDetail extends RouteRunSummary {
  output: string;
  error: string;
  chain_run: string | null;
}

export type ChainStepStatus = "pending" | "running" | "done" | "error";

export interface ChainStepState {
  id: string;
  step_id: string;
  label: string;
  order: number;
  status: ChainStepStatus;
  output: string | null;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface ChainRunSummary {
  id: string;
  query: string;
  status: "running" | "done" | "error";
  model: string;
  created_at: string;
  completed_at: string | null;
}

export interface ChainRunDetail extends ChainRunSummary {
  steps: ChainStepState[];
}

export type ParallelStrategy = "sectioning" | "voting";

export type VoteVerdict = "buy" | "hold" | "sell";

export interface ParallelTaskState {
  id: string;
  task_id: string;
  label: string;
  order: number;
  status: ChainStepStatus; // reuse pending|running|done|error
  output: string | null;
  vote: string | null; // voting only
  error: string | null;
}

export interface ParallelRunSummary {
  id: string;
  query: string;
  strategy: ParallelStrategy;
  n: number;
  status: "running" | "done" | "error";
  model: string;
  created_at: string;
  completed_at: string | null;
}

export interface ParallelRunDetail extends ParallelRunSummary {
  output: string;
  tally: Record<VoteVerdict, number> | null;
  error: string;
  tasks: ParallelTaskState[];
}

export interface ReactStepState {
  id: string;
  order: number;
  thought: string;
  tool: string | null;
  tool_args: Record<string, unknown> | null;
  observation: string | null;
  is_answer: boolean;
  status: ChainStepStatus; // running | done | error (pending unused)
  error: string | null;
}

export interface ReactRunSummary {
  id: string;
  query: string;
  max_steps: number;
  status: "running" | "done" | "error";
  model: string;
  created_at: string;
  completed_at: string | null;
}

export interface ReactRunDetail extends ReactRunSummary {
  output: string;
  error: string;
  steps: ReactStepState[];
}

export interface EvalOptIterationState {
  id: string;
  order: number;
  draft: string;
  score: number | null;
  feedback: string;
  passed: boolean;
  status: ChainStepStatus; // running | done | error (pending unused)
  error: string | null;
}

export interface EvalOptRunSummary {
  id: string;
  query: string;
  max_iterations: number;
  threshold: number;
  status: "running" | "done" | "error";
  model: string;
  best_score: number | null;
  created_at: string;
  completed_at: string | null;
}

export interface EvalOptRunDetail extends EvalOptRunSummary {
  output: string;
  error: string;
  iterations: EvalOptIterationState[];
}

export interface PlanStepSpec {
  task: string;
  tool: string | null;
  args: Record<string, unknown> | null;
}

export interface PlanExecStepState {
  id: string;
  order: number;
  task: string;
  tool: string | null;
  tool_args: Record<string, unknown> | null;
  observation: string | null;
  result: string | null;
  status: ChainStepStatus; // running | done | error (pending unused)
  error: string | null;
}

export interface PlanExecRunSummary {
  id: string;
  query: string;
  max_steps: number;
  allow_replan: boolean;
  status: "running" | "done" | "error";
  model: string;
  replans: number;
  created_at: string;
  completed_at: string | null;
}

export interface PlanExecRunDetail extends PlanExecRunSummary {
  plan: PlanStepSpec[] | null;
  output: string;
  error: string;
  steps: PlanExecStepState[];
}

export interface OrchestratorSubtaskSpec {
  task: string;
  focus: string;
  tool: string | null;
  args: Record<string, unknown> | null;
}

export interface OrchestratorWorkerState {
  id: string;
  worker_id: string;
  label: string;
  task: string;
  order: number;
  tool: string | null;
  tool_args: Record<string, unknown> | null;
  observation: string | null;
  output: string | null;
  status: ChainStepStatus; // pending | running | done | error
  error: string | null;
}

export interface OrchestratorRunSummary {
  id: string;
  query: string;
  max_workers: number;
  status: "running" | "done" | "error";
  model: string;
  created_at: string;
  completed_at: string | null;
}

export interface OrchestratorRunDetail extends OrchestratorRunSummary {
  plan: OrchestratorSubtaskSpec[] | null;
  output: string;
  error: string;
  workers: OrchestratorWorkerState[];
}

export interface MultiAgentToolCall {
  tool: string;
  args: Record<string, unknown> | null;
  observation: string | null;
}

export interface MultiAgentStepState {
  id: string;
  agent_id: string;
  label: string;
  order: number;
  input: string | null;
  tool_calls: MultiAgentToolCall[] | null;
  output: string | null;
  status: ChainStepStatus; // pending | running | done | error
  error: string | null;
}

export interface MultiAgentRunSummary {
  id: string;
  query: string;
  max_tools: number;
  status: "running" | "done" | "error";
  model: string;
  created_at: string;
  completed_at: string | null;
}

export interface MultiAgentRunDetail extends MultiAgentRunSummary {
  agents: string[] | null;
  route_reason: string;
  output: string;
  error: string;
  steps: MultiAgentStepState[];
}

export interface DagNodeState {
  id: string;
  node_id: string;
  label: string;
  task: string;
  wave: number;
  order: number;
  depends_on: string[];
  tool: string | null;
  tool_args: Record<string, unknown> | null;
  observation: string | null;
  output: string | null;
  status: ChainStepStatus; // pending | running | done | error
  error: string | null;
}

export interface DagPlanNode {
  id: string;
  task: string;
  focus: string;
  tool: string | null;
  args: Record<string, unknown> | null;
  depends_on: string[];
  wave: number;
}

export interface DagRunSummary {
  id: string;
  query: string;
  max_nodes: number;
  status: "running" | "done" | "error";
  model: string;
  created_at: string;
  completed_at: string | null;
}

export interface DagRunDetail extends DagRunSummary {
  plan: { nodes: DagPlanNode[]; waves: string[][] } | null;
  output: string;
  error: string;
  nodes: DagNodeState[];
}

export type AutonomousAction = "tool" | "subagent" | "reason";

export interface AutonomousSubagentStep {
  thought: string;
  tool: string;
  args: Record<string, unknown> | null;
  observation: string;
}

export interface AutonomousCycleState {
  id: string;
  index: number;
  reflection: string | null;
  task: string | null;
  action: AutonomousAction;
  tool: string | null;
  tool_args: Record<string, unknown> | null;
  observation: string | null;
  spawned: boolean;
  subagent_steps: AutonomousSubagentStep[] | null;
  output: string | null;
  backlog: string[] | null;
  goal_complete: boolean;
  status: ChainStepStatus; // pending | running | done | error
  error: string | null;
}

export type AutonomousStopReason = "" | "complete" | "no_progress" | "budget" | "error";

export interface AutonomousRunSummary {
  id: string;
  query: string;
  max_cycles: number;
  max_subagents: number;
  stop_reason: AutonomousStopReason;
  status: "running" | "done" | "error";
  model: string;
  created_at: string;
  completed_at: string | null;
}

export interface AutonomousRunDetail extends AutonomousRunSummary {
  goal: string;
  backlog: string[] | null;
  output: string;
  error: string;
  cycles: AutonomousCycleState[];
}

export type RouteMode = "llm" | "semantic";

export interface LLMSettings {
  base_url: string;
  main_model: string;
  classifier_model: string;
  embed_model: string;
  timeout: number;
  num_parallel: number;
  route_mode: RouteMode;
  route_threshold: number;
  react_max_steps: number;
  eval_max_iterations: number;
  eval_threshold: number;
  plan_max_steps: number;
  plan_max_replans: number;
  orch_max_workers: number;
  multiagent_max_tools: number;
  dag_max_nodes: number;
  auto_max_cycles: number;
  auto_max_subagents: number;
  auto_subagent_steps: number;
  auto_no_progress: number;
  // Browser agent (/browse). Off by default - it is the only agent that leaves the network.
  browser_enabled: boolean;
  browser_provider: "anthropic" | "ollama";
  browser_model: string;
  browser_max_steps: number;
  browser_timeout_s: number;
  browser_headless: boolean;
  browser_allowed_domains: string;
  updated_at: string;
}

export type LLMSettingsUpdate = Omit<LLMSettings, "updated_at">;
