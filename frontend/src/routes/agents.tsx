import { useEffect, useRef, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Markdown } from "@/components/Markdown";
import {
  cancelRun,
  fetchAllRuns,
  fetchAutonomousRunDetail,
  fetchChainRunDetail,
  fetchDagRunDetail,
  fetchEvalOptRunDetail,
  fetchModels,
  fetchMultiAgentRunDetail,
  fetchOrchestratorRunDetail,
  fetchParallelRunDetail,
  fetchPlanRunDetail,
  fetchReactRunDetail,
  fetchRouteRunDetail,
  type HistoryAgentType,
  type HistoryRunSummary,
} from "@/api/llm";
import { queryKeys } from "@/api/queryKeys";
import { AppShell } from "@/components/layout/AppShell";
import { WorkspaceSwitch } from "@/components/layout/WorkspaceSwitch";
import { SettingsDrawer } from "@/components/llm/SettingsDrawer";
import { Button } from "@/components/ui/button";
import {
  loadAgentsSession,
  saveAgentsSession,
  type AgentsSession,
} from "@/lib/agentsSession";
import { useAutonomous } from "@/hooks/useAutonomous";
import { useDag } from "@/hooks/useDag";
import { useElapsed } from "@/hooks/useElapsed";
import { useEvaluate } from "@/hooks/useEvaluate";
import { useMultiAgent } from "@/hooks/useMultiAgent";
import { useOrchestrator } from "@/hooks/useOrchestrator";
import { useParallel } from "@/hooks/useParallel";
import { usePlanExecute } from "@/hooks/usePlanExecute";
import { usePromptChain } from "@/hooks/usePromptChain";
import { useReact } from "@/hooks/useReact";
import { useRouting } from "@/hooks/useRouting";
import { useSinglePrompt } from "@/hooks/useSinglePrompt";
import { cn } from "@/lib/utils";
import type {
  AutonomousCycleState,
  ChainStepState,
  ComparableAgentType,
  DagNodeState,
  EvalOptIterationState,
  MultiAgentStepState,
  OrchestratorSubtaskSpec,
  OrchestratorWorkerState,
  ParallelStrategy,
  ParallelTaskState,
  PlanExecStepState,
  PlanStepSpec,
  ReactStepState,
  RouteClassification,
  RouteLabel,
  VoteVerdict,
} from "@/types/llm";

export const Route = createFileRoute("/agents")({
  component: AgentsPage,
});

const STEP_ORDER = ["classify", "research", "synthesise", "format"];

const PLACEHOLDERS = [
  "Analyse Apple's revenue growth over 5 years",
  "Compare MSFT vs GOOG on profitability",
  "What is Tesla's debt situation?",
];

// ---------------------------------------------------------------------------
// Agent registry — comparable agent types
// ---------------------------------------------------------------------------

const COMPARABLE_TYPES: ComparableAgentType[] = [
  "single",
  "chain",
  "route",
  "parallel",
  "react",
  "evaluate",
  "plan",
  "orchestrate",
  "multiagent",
  "dag",
  "autonomous",
];

const AGENT_REGISTRY: Record<
  ComparableAgentType,
  { label: string; blurb: string }
> = {
  single: {
    label: "Single Prompt",
    blurb: "One direct Ollama call. Fastest, no intermediate steps.",
  },
  chain: {
    label: "Prompt Chain",
    blurb:
      "Fixed 4-step pipeline: classify -> research -> synthesise -> format.",
  },
  route: {
    label: "Routing",
    blurb: "Classifier picks simple / analysis / deep-research path.",
  },
  parallel: {
    label: "Parallel",
    blurb:
      "Fan out concurrently - sectioning or N-way voting - then aggregate.",
  },
  react: {
    label: "ReAct",
    blurb: "LLM picks tools in a loop - reason, act, observe, repeat.",
  },
  evaluate: {
    label: "Evaluator-Optimizer",
    blurb: "Generate, self-critique, revise until it clears the quality bar.",
  },
  plan: {
    label: "Plan-and-Execute",
    blurb: "Plan all steps upfront, then execute them in order.",
  },
  orchestrate: {
    label: "Orchestrator-Workers",
    blurb:
      "Lead LLM decomposes the task on the fly, workers run in parallel, then synthesise.",
  },
  multiagent: {
    label: "Multi-Agent",
    blurb:
      "Supervisor routes a Researcher -> Analyst -> Writer pipeline; each is a specialised agent with its own tools.",
  },
  dag: {
    label: "Multi-Agent DAG",
    blurb:
      "Orchestrator builds a dependency graph; independent nodes run concurrently in waves, dependents consume upstream outputs.",
  },
  autonomous: {
    label: "Autonomous",
    blurb:
      "Goal-driven loop: reflect, self-assign tasks, optionally spawn sub-agents, replan, and stop when the goal is met (bounded).",
  },
};

interface AgentController {
  type: ComparableAgentType;
  run: (query: string, model?: string) => void;
  reset: () => void;
  isRunning: boolean;
  status: RunStatus;
  elapsedMs?: number | null;
  renderProcess: (query: string) => React.ReactNode;
  renderResult: () => React.ReactNode;
}

// ---------------------------------------------------------------------------
// Step input derivation
// ---------------------------------------------------------------------------

function deriveStepInput(
  stepId: string,
  query: string,
  steps: ChainStepState[],
): string | null {
  const out = (id: string) =>
    steps.find((s) => s.step_id === id)?.output ?? null;
  switch (stepId) {
    case "classify":
      return query || null;
    case "research":
      return out("classify");
    case "synthesise": {
      const c = out("classify");
      const r = out("research");
      if (!c || !r) return null;
      return (
        "Query: " +
        query +
        "\n\nClassify: " +
        c.slice(0, 400) +
        "\n\nResearch: " +
        r.slice(0, 400)
      );
    }
    case "format":
      return out("synthesise");
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// StepCard
// ---------------------------------------------------------------------------

function StepCard({
  step,
  input,
}: {
  step: ChainStepState;
  input: string | null;
}) {
  const [inputExpanded, setInputExpanded] = useState(false);
  const [outputExpanded, setOutputExpanded] = useState(false);

  const borderClass = {
    pending: "border-border",
    running: "border-blue-500",
    done: "border-green-500",
    error: "border-red-500",
  }[step.status];

  const icon = {
    pending: (
      <span className="h-4 w-4 rounded-full border-2 border-muted-foreground" />
    ),
    running: (
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
    ),
    done: (
      <svg className="h-4 w-4 text-green-500" viewBox="0 0 16 16" fill="none">
        <path
          d="M3 8l3.5 3.5L13 5"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    ),
    error: (
      <svg className="h-4 w-4 text-red-500" viewBox="0 0 16 16" fill="none">
        <path
          d="M4 4l8 8M12 4l-8 8"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
    ),
  }[step.status];

  const elapsed =
    step.started_at && step.completed_at
      ? (
          (new Date(step.completed_at).getTime() -
            new Date(step.started_at).getTime()) /
          1000
        ).toFixed(1) + "s"
      : null;

  return (
    <div
      className={cn("rounded-lg border-2 p-3 transition-colors", borderClass)}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {icon}
          <span className="text-sm font-medium">{step.label}</span>
        </div>
        {elapsed && (
          <span className="text-[10px] text-muted-foreground">{elapsed}</span>
        )}
      </div>

      {step.status === "running" && (
        <p className="mt-2 text-xs text-muted-foreground">Running...</p>
      )}

      {input !== null && (
        <div className="mt-2 border-t pt-2">
          <button
            className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground w-full text-left"
            onClick={() => setInputExpanded(!inputExpanded)}
          >
            <span>{inputExpanded ? "▾" : "▸"}</span>
            <span>Input</span>
          </button>
          {inputExpanded && (
            <pre className="mt-1 rounded bg-muted p-2 text-xs whitespace-pre-wrap break-words max-h-32 overflow-y-auto">
              {input}
            </pre>
          )}
        </div>
      )}

      {(step.status === "done" || step.status === "error") && (
        <div className="mt-2 border-t pt-2">
          <button
            className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground w-full text-left"
            onClick={() => setOutputExpanded(!outputExpanded)}
          >
            <span>{outputExpanded ? "▾" : "▸"}</span>
            <span>Output</span>
          </button>
          {step.status === "error" ? (
            <p className="mt-1 text-xs text-red-500">{step.error}</p>
          ) : outputExpanded ? (
            <pre className="mt-1 rounded bg-muted p-2 text-xs whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
              {step.output}
            </pre>
          ) : (
            <p
              className="mt-1 line-clamp-3 cursor-pointer text-xs text-muted-foreground hover:text-foreground"
              onClick={() => setOutputExpanded(true)}
            >
              {step.output}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

type RunStatus = "running" | "done" | "error" | "idle";

function StatusBadge({ status }: { status: RunStatus }) {
  if (status === "idle") return null;
  const cls: Record<Exclude<RunStatus, "idle">, string> = {
    running: "bg-blue-100 text-blue-700",
    done: "bg-green-100 text-green-700",
    error: "bg-red-100 text-red-700",
  };
  const label: Record<Exclude<RunStatus, "idle">, string> = {
    running: "running...",
    done: "done",
    error: "error",
  };
  return (
    <span
      className={cn("rounded px-2 py-0.5 text-[10px] font-medium", cls[status])}
    >
      {label[status]}
    </span>
  );
}

// ---------------------------------------------------------------------------
// WorkflowChip — compact active-workflow summary with a status dot + remove
// ---------------------------------------------------------------------------

const STATUS_DOT: Record<RunStatus, string> = {
  idle: "bg-muted-foreground/40",
  running: "bg-blue-500 animate-pulse",
  done: "bg-green-500",
  error: "bg-red-500",
};

function WorkflowChip({
  label,
  status,
  onRemove,
}: {
  label: string;
  status: RunStatus;
  onRemove?: () => void;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border bg-background px-2.5 py-0.5 text-xs">
      <span className={cn("h-1.5 w-1.5 rounded-full", STATUS_DOT[status])} />
      <span>{label}</span>
      {onRemove && (
        <button
          type="button"
          aria-label={`Remove ${label}`}
          className="leading-none text-muted-foreground hover:text-foreground"
          onClick={onRemove}
        >
          ×
        </button>
      )}
    </span>
  );
}

// ---------------------------------------------------------------------------
// SinglePromptPanel
// ---------------------------------------------------------------------------

function SinglePromptPanel({
  result,
  isRunning,
  elapsedMs,
  error,
}: {
  result: string | null;
  isRunning: boolean;
  elapsedMs: number | null;
  error: string | null;
}) {
  const status: RunStatus = isRunning
    ? "running"
    : error
      ? "error"
      : result
        ? "done"
        : "idle";

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Single Prompt</h2>
        <div className="flex items-center gap-2">
          {elapsedMs !== null && (
            <span className="text-xs text-muted-foreground">
              {(elapsedMs / 1000).toFixed(1)}s
            </span>
          )}
          <StatusBadge status={status} />
        </div>
      </div>
      {isRunning && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
          Running...
        </div>
      )}
      {error && <p className="text-sm text-red-500">{error}</p>}
      {result && (
        <div className="prose prose-sm max-w-none dark:prose-invert">
          <Markdown>{result}</Markdown>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ChainPanel
// ---------------------------------------------------------------------------

function ChainPanel({
  steps,
  runId,
  query,
}: {
  steps: ChainStepState[];
  runId: string | null;
  query: string;
}) {
  const orderedSteps = STEP_ORDER.map(
    (id) => steps.find((s) => s.step_id === id)!,
  ).filter(Boolean);
  const formatStep = steps.find((s) => s.step_id === "format");
  const showReport = formatStep?.status === "done" && !!formatStep.output;

  return (
    <div className="space-y-3">
      {runId && (
        <p className="text-[10px] text-muted-foreground">Run ID: {runId}</p>
      )}
      <div className="flex flex-col gap-2">
        {orderedSteps.map((step, i) => (
          <div key={step.step_id}>
            <StepCard
              step={step}
              input={deriveStepInput(step.step_id, query, steps)}
            />
            {i < orderedSteps.length - 1 && (
              <div className="flex justify-center py-1">
                <span className="text-sm text-muted-foreground">↓</span>
              </div>
            )}
          </div>
        ))}
      </div>
      {showReport && (
        <div className="rounded-lg border p-4">
          <h2 className="mb-3 text-sm font-semibold">Final Report</h2>
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <Markdown>{formatStep!.output!}</Markdown>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// RouteDecisionCard
// ---------------------------------------------------------------------------

const ROUTE_BADGE: Record<RouteLabel, { label: string; cls: string }> = {
  simple: { label: "SIMPLE", cls: "bg-blue-100 text-blue-700" },
  analysis: { label: "ANALYSIS", cls: "bg-amber-100 text-amber-700" },
  deep_research: {
    label: "DEEP RESEARCH",
    cls: "bg-purple-100 text-purple-700",
  },
};

function RouteDecisionCard({
  classification,
}: {
  classification: RouteClassification;
}) {
  const badge = ROUTE_BADGE[classification.route];
  return (
    <div className="space-y-2 rounded-lg border p-4">
      <h2 className="text-sm font-semibold">Route Decided</h2>
      <div className="grid grid-cols-[90px_1fr] gap-x-3 gap-y-1.5 text-sm">
        <span className="text-muted-foreground">Path</span>
        <span>
          <span
            className={cn(
              "rounded px-2 py-0.5 text-[10px] font-semibold",
              badge.cls,
            )}
          >
            {badge.label}
          </span>
        </span>
        <span className="text-muted-foreground">Complexity</span>
        <span className="capitalize">{classification.complexity}</span>
        {classification.tickers.length > 0 && (
          <>
            <span className="text-muted-foreground">Tickers</span>
            <span className="font-medium">
              {classification.tickers.join(", ")}
            </span>
          </>
        )}
        <span className="text-muted-foreground">Reason</span>
        <span className="text-muted-foreground italic">
          {classification.reason}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// RoutingPanel
// ---------------------------------------------------------------------------

function RoutingPanel({
  routing,
  query,
}: {
  routing: ReturnType<typeof useRouting>;
  query: string;
}) {
  const {
    classification,
    route,
    isClassifying,
    isExecuting,
    chainSteps,
    output,
    error,
  } = routing;

  return (
    <div className="space-y-3">
      {isClassifying && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
          Classifying query...
        </div>
      )}

      {error && <p className="text-sm text-red-500">{error}</p>}

      {classification && <RouteDecisionCard classification={classification} />}

      {route === "deep_research" && (classification || isExecuting) && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Executing: Deep Research
          </h3>
          <div className="flex flex-col gap-2">
            {STEP_ORDER.map((id) => chainSteps.find((s) => s.step_id === id)!)
              .filter(Boolean)
              .map((step, i, arr) => (
                <div key={step.step_id}>
                  <StepCard
                    step={step}
                    input={deriveStepInput(step.step_id, query, chainSteps)}
                  />
                  {i < arr.length - 1 && (
                    <div className="flex justify-center py-1">
                      <span className="text-sm text-muted-foreground">↓</span>
                    </div>
                  )}
                </div>
              ))}
          </div>
        </div>
      )}

      {output && (
        <div className="rounded-lg border p-4">
          <h2 className="mb-3 text-sm font-semibold">Result</h2>
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <Markdown>{output}</Markdown>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// StrategyToggle
// ---------------------------------------------------------------------------

function StrategyToggle({
  strategy,
  n,
  onStrategyChange,
  onNChange,
  disabled,
}: {
  strategy: ParallelStrategy;
  n: number;
  onStrategyChange: (s: ParallelStrategy) => void;
  onNChange: (n: number) => void;
  disabled: boolean;
}) {
  const options: { value: ParallelStrategy; label: string }[] = [
    { value: "sectioning", label: "Sectioning" },
    { value: "voting", label: "Voting" },
  ];
  return (
    <div className="flex items-center gap-3">
      <div className="flex w-fit overflow-hidden rounded-md border">
        {options.map(({ value, label }, i) => (
          <button
            key={value}
            type="button"
            disabled={disabled}
            className={cn(
              "px-3 py-1 text-sm font-medium transition-colors disabled:opacity-50",
              strategy === value
                ? "bg-primary text-primary-foreground"
                : "bg-background text-muted-foreground hover:bg-muted hover:text-foreground",
              i < options.length - 1 && "border-r",
            )}
            onClick={() => onStrategyChange(value)}
          >
            {label}
          </button>
        ))}
      </div>
      {strategy === "voting" && (
        <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <span>Votes</span>
          <input
            type="number"
            min={2}
            max={5}
            value={n}
            disabled={disabled}
            onChange={(e) =>
              onNChange(Math.min(5, Math.max(2, Number(e.target.value) || 2)))
            }
            className="w-14 rounded-md border px-2 py-1 text-sm disabled:opacity-50"
          />
        </label>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// VoteTally
// ---------------------------------------------------------------------------

const VERDICT_BADGE: Record<VoteVerdict, string> = {
  buy: "bg-green-100 text-green-700",
  hold: "bg-amber-100 text-amber-700",
  sell: "bg-red-100 text-red-700",
};

function consensusFromTally(tally: Record<VoteVerdict, number>): VoteVerdict {
  const verdicts: VoteVerdict[] = ["buy", "hold", "sell"];
  const top = Math.max(...verdicts.map((v) => tally[v]));
  const winners = verdicts.filter((v) => tally[v] === top);
  return winners.length === 1 ? winners[0] : "hold";
}

function VoteTally({ tally }: { tally: Record<VoteVerdict, number> }) {
  const verdicts: VoteVerdict[] = ["buy", "hold", "sell"];
  const consensus = consensusFromTally(tally);
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border p-3 text-sm">
      <div className="flex items-center gap-2">
        {verdicts.map((v) => (
          <span
            key={v}
            className={cn(
              "rounded px-2 py-0.5 text-[11px] font-medium",
              VERDICT_BADGE[v],
            )}
          >
            {v} {tally[v]}
          </span>
        ))}
      </div>
      <span className="text-muted-foreground">-&gt;</span>
      <span className="font-semibold">
        Consensus:{" "}
        <span
          className={cn(
            "rounded px-2 py-0.5 text-[11px] font-semibold",
            VERDICT_BADGE[consensus],
          )}
        >
          {consensus.toUpperCase()}
        </span>
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ParallelPanel
// ---------------------------------------------------------------------------

function taskToStep(task: ParallelTaskState): ChainStepState {
  const label = task.vote ? `${task.label} (${task.vote})` : task.label;
  return {
    id: task.id,
    step_id: task.task_id,
    label,
    order: task.order,
    status: task.status,
    output: task.output,
    error: task.error,
    started_at: null,
    completed_at: null,
  };
}

function ParallelPanel({
  parallel,
  controls,
}: {
  parallel: ReturnType<typeof useParallel>;
  controls?: {
    strategy: ParallelStrategy;
    n: number;
    onStrategyChange: (s: ParallelStrategy) => void;
    onNChange: (n: number) => void;
    disabled: boolean;
  };
}) {
  const { strategy, tasks, tally, output, isRunning, error } = parallel;

  return (
    <div className="space-y-3">
      {controls && (
        <StrategyToggle
          strategy={controls.strategy}
          n={controls.n}
          onStrategyChange={controls.onStrategyChange}
          onNChange={controls.onNChange}
          disabled={controls.disabled}
        />
      )}

      {isRunning && tasks.length === 0 && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
          Fanning out...
        </div>
      )}

      {error && <p className="text-sm text-red-500">{error}</p>}

      {tasks.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Fan-out (concurrent) - {strategy}
          </h3>
          <div className="grid gap-2 sm:grid-cols-2">
            {tasks.map((task) => (
              <StepCard
                key={task.task_id}
                step={taskToStep(task)}
                input={null}
              />
            ))}
          </div>
        </div>
      )}

      {tally && <VoteTally tally={tally} />}

      {output && (
        <div className="rounded-lg border p-4">
          <h2 className="mb-3 text-sm font-semibold">Result</h2>
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <Markdown>{output}</Markdown>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ReactPanel
// ---------------------------------------------------------------------------

function ReactStepCard({ step }: { step: ReactStepState }) {
  const [obsExpanded, setObsExpanded] = useState(false);

  const borderClass =
    step.status === "error" ? "border-red-500" : "border-green-500";

  if (step.is_answer) {
    return (
      <div className="rounded-lg border-2 border-green-500 p-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">Final reasoning</span>
        </div>
        {step.thought && (
          <p className="mt-1 text-xs text-muted-foreground italic">
            {step.thought}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className={cn("rounded-lg border-2 p-3", borderClass)}>
      {step.thought && (
        <div>
          <span className="text-xs font-semibold text-muted-foreground">
            Thought
          </span>
          <p className="text-sm">{step.thought}</p>
        </div>
      )}
      {step.tool && (
        <div className="mt-2">
          <span className="text-xs font-semibold text-muted-foreground">
            Action
          </span>
          <p className="font-mono text-xs">
            {step.tool}({step.tool_args ? JSON.stringify(step.tool_args) : ""})
          </p>
        </div>
      )}
      {step.status === "error" ? (
        <p className="mt-2 text-xs text-red-500">{step.error}</p>
      ) : (
        step.observation && (
          <div className="mt-2 border-t pt-2">
            <button
              className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground w-full text-left"
              onClick={() => setObsExpanded(!obsExpanded)}
            >
              <span>{obsExpanded ? "▾" : "▸"}</span>
              <span>Observation</span>
            </button>
            {obsExpanded ? (
              <pre className="mt-1 rounded bg-muted p-2 text-xs whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
                {step.observation}
              </pre>
            ) : (
              <p
                className="mt-1 line-clamp-2 cursor-pointer text-xs text-muted-foreground hover:text-foreground"
                onClick={() => setObsExpanded(true)}
              >
                {step.observation}
              </p>
            )}
          </div>
        )
      )}
    </div>
  );
}

function ReactPanel({ react }: { react: ReturnType<typeof useReact> }) {
  const { steps, maxSteps, output, isRunning, error } = react;
  const toolSteps = steps.filter((s) => !s.is_answer).length;

  return (
    <div className="space-y-3">
      <p className="text-[10px] text-muted-foreground">
        Tool calls: {toolSteps} / {maxSteps}
      </p>

      {isRunning && steps.length === 0 && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
          Reasoning...
        </div>
      )}

      {error && <p className="text-sm text-red-500">{error}</p>}

      <div className="flex flex-col gap-2">
        {steps.map((step, i) => (
          <div key={`${step.order}-${i}`}>
            <div className="flex items-start gap-2">
              <span className="mt-2 text-xs font-semibold text-muted-foreground">
                {i + 1}.
              </span>
              <div className="flex-1">
                <ReactStepCard step={step} />
              </div>
            </div>
            {i < steps.length - 1 && (
              <div className="flex justify-center py-1">
                <span className="text-sm text-muted-foreground">↓</span>
              </div>
            )}
          </div>
        ))}
      </div>

      {isRunning && steps.length > 0 && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
          Thinking about the next step...
        </div>
      )}

      {output && (
        <div className="rounded-lg border p-4">
          <h2 className="mb-3 text-sm font-semibold">Final Answer</h2>
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <Markdown>{output}</Markdown>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// EvaluatePanel
// ---------------------------------------------------------------------------

function EvalIterationCard({
  iteration,
  threshold,
}: {
  iteration: EvalOptIterationState;
  threshold: number;
}) {
  const [draftExpanded, setDraftExpanded] = useState(false);
  const borderClass =
    iteration.status === "error"
      ? "border-red-500"
      : iteration.passed
        ? "border-green-500"
        : "border-amber-500";

  return (
    <div className={cn("rounded-lg border-2 p-3", borderClass)}>
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium">
          Score {iteration.score ?? "?"}/10
        </span>
        <span
          className={cn(
            "rounded px-2 py-0.5 text-[10px] font-medium",
            iteration.passed
              ? "bg-green-100 text-green-700"
              : "bg-amber-100 text-amber-700",
          )}
        >
          {iteration.passed ? "PASS" : `below bar (${threshold})`}
        </span>
      </div>

      {iteration.status === "error" ? (
        <p className="mt-2 text-xs text-red-500">
          {iteration.error ?? "Could not parse evaluator output."}
        </p>
      ) : (
        iteration.feedback && (
          <div className="mt-2">
            <span className="text-xs font-semibold text-muted-foreground">
              Feedback
            </span>
            <p className="text-sm">{iteration.feedback}</p>
          </div>
        )
      )}

      {iteration.draft && (
        <div className="mt-2 border-t pt-2">
          <button
            className="flex w-full items-center gap-1 text-left text-xs font-medium text-muted-foreground hover:text-foreground"
            onClick={() => setDraftExpanded(!draftExpanded)}
          >
            <span>{draftExpanded ? "▾" : "▸"}</span>
            <span>Graded draft</span>
          </button>
          {draftExpanded && (
            <div className="prose prose-sm mt-1 max-h-48 max-w-none overflow-y-auto dark:prose-invert">
              <Markdown>{iteration.draft}</Markdown>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function EvaluatePanel({
  evaluate,
}: {
  evaluate: ReturnType<typeof useEvaluate>;
}) {
  const {
    draft,
    iterations,
    maxIterations,
    threshold,
    output,
    bestScore,
    isRunning,
    error,
  } = evaluate;

  return (
    <div className="space-y-3">
      <p className="text-[10px] text-muted-foreground">
        Iterations: {iterations.length} / {maxIterations} · quality bar{" "}
        {threshold}/10
      </p>

      {isRunning && !draft && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
          Drafting...
        </div>
      )}

      {error && <p className="text-sm text-red-500">{error}</p>}

      {draft && (
        <div className="rounded-lg border p-3">
          <span className="text-xs font-semibold text-muted-foreground">
            Initial draft
          </span>
          <div className="prose prose-sm mt-1 max-w-none dark:prose-invert">
            <Markdown>{draft}</Markdown>
          </div>
        </div>
      )}

      <div className="flex flex-col gap-2">
        {iterations.map((iteration, i) => (
          <div key={`${iteration.order}-${i}`}>
            <div className="flex items-start gap-2">
              <span className="mt-2 text-xs font-semibold text-muted-foreground">
                {i + 1}.
              </span>
              <div className="flex-1">
                <EvalIterationCard
                  iteration={iteration}
                  threshold={threshold}
                />
              </div>
            </div>
            {i < iterations.length - 1 && (
              <div className="flex justify-center py-1">
                <span className="text-sm text-muted-foreground">↓</span>
              </div>
            )}
          </div>
        ))}
      </div>

      {isRunning && iterations.length > 0 && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
          Critiquing and revising...
        </div>
      )}

      {output && (
        <div className="rounded-lg border p-4">
          <h2 className="mb-3 text-sm font-semibold">
            Final Answer{bestScore !== null ? ` (best, ${bestScore}/10)` : ""}
          </h2>
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <Markdown>{output}</Markdown>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// PlanExecutePanel
// ---------------------------------------------------------------------------

function PlanStepCard({ step }: { step: PlanExecStepState }) {
  const [obsExpanded, setObsExpanded] = useState(false);
  const borderClass =
    step.status === "error" ? "border-red-500" : "border-green-500";

  return (
    <div className={cn("rounded-lg border-2 p-3", borderClass)}>
      <div>
        <span className="text-xs font-semibold text-muted-foreground">
          Task
        </span>
        <p className="text-sm">{step.task}</p>
      </div>
      {step.tool && (
        <div className="mt-2">
          <span className="text-xs font-semibold text-muted-foreground">
            Tool
          </span>
          <p className="font-mono text-xs">
            {step.tool}({step.tool_args ? JSON.stringify(step.tool_args) : ""})
          </p>
        </div>
      )}
      {step.observation && (
        <div className="mt-2 border-t pt-2">
          <button
            className="flex w-full items-center gap-1 text-left text-xs font-medium text-muted-foreground hover:text-foreground"
            onClick={() => setObsExpanded(!obsExpanded)}
          >
            <span>{obsExpanded ? "▾" : "▸"}</span>
            <span>Observation</span>
          </button>
          {obsExpanded ? (
            <pre className="mt-1 max-h-48 overflow-y-auto rounded bg-muted p-2 text-xs break-words whitespace-pre-wrap">
              {step.observation}
            </pre>
          ) : (
            <p
              className="mt-1 line-clamp-1 cursor-pointer text-xs text-muted-foreground hover:text-foreground"
              onClick={() => setObsExpanded(true)}
            >
              {step.observation}
            </p>
          )}
        </div>
      )}
      {step.result && (
        <div className="mt-2 border-t pt-2">
          <span className="text-xs font-semibold text-muted-foreground">
            Result
          </span>
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <Markdown>{step.result}</Markdown>
          </div>
        </div>
      )}
    </div>
  );
}

function PlanList({ plan }: { plan: PlanStepSpec[] }) {
  return (
    <div className="rounded-lg border p-3">
      <span className="text-xs font-semibold text-muted-foreground">Plan</span>
      <ol className="mt-1 space-y-1">
        {plan.map((s, i) => (
          <li key={i} className="flex items-baseline gap-2 text-sm">
            <span className="text-xs font-semibold text-muted-foreground">
              {i + 1}.
            </span>
            <span className="flex-1">{s.task}</span>
            <span className="font-mono text-[10px] text-muted-foreground">
              [{s.tool ?? "reason"}]
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function PlanExecutePanel({
  planExec,
}: {
  planExec: ReturnType<typeof usePlanExecute>;
}) {
  const {
    plan,
    steps,
    maxSteps,
    allowReplan,
    output,
    replans,
    isRunning,
    error,
  } = planExec;

  return (
    <div className="space-y-3">
      <p className="text-[10px] text-muted-foreground">
        Max steps: {maxSteps} · replan {allowReplan ? "on" : "off"}
        {replans > 0 && (
          <span className="ml-2 rounded bg-amber-100 px-2 py-0.5 font-medium text-amber-700">
            replanned x{replans}
          </span>
        )}
      </p>

      {isRunning && !plan && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
          Planning...
        </div>
      )}

      {error && <p className="text-sm text-red-500">{error}</p>}

      {plan && <PlanList plan={plan} />}

      {steps.length > 0 && (
        <div className="flex flex-col gap-2">
          <span className="text-xs font-semibold text-muted-foreground">
            Execution
          </span>
          {steps.map((step, i) => (
            <div key={`${step.order}-${i}`}>
              <div className="flex items-start gap-2">
                <span className="mt-2 text-xs font-semibold text-muted-foreground">
                  {i + 1}.
                </span>
                <div className="flex-1">
                  <PlanStepCard step={step} />
                </div>
              </div>
              {i < steps.length - 1 && (
                <div className="flex justify-center py-1">
                  <span className="text-sm text-muted-foreground">↓</span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {isRunning && steps.length > 0 && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
          Executing the plan...
        </div>
      )}

      {output && (
        <div className="rounded-lg border p-4">
          <h2 className="mb-3 text-sm font-semibold">Final Answer</h2>
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <Markdown>{output}</Markdown>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// OrchestratorPanel
// ---------------------------------------------------------------------------

function workerToStep(worker: OrchestratorWorkerState): PlanExecStepState {
  return {
    id: worker.id,
    order: worker.order,
    task: worker.task,
    tool: worker.tool,
    tool_args: worker.tool_args,
    observation: worker.observation,
    result: worker.output,
    status: worker.status,
    error: worker.error,
  };
}

function SubtaskList({ subtasks }: { subtasks: OrchestratorSubtaskSpec[] }) {
  return (
    <div className="rounded-lg border p-3">
      <span className="text-xs font-semibold text-muted-foreground">
        Decomposition
      </span>
      <ol className="mt-1 space-y-1">
        {subtasks.map((s, i) => (
          <li key={i} className="flex items-baseline gap-2 text-sm">
            <span className="text-xs font-semibold text-muted-foreground">
              {i + 1}.
            </span>
            <span className="flex-1">{s.task}</span>
            <span className="font-mono text-[10px] text-muted-foreground">
              [{s.focus}] [{s.tool ?? "reason"}]
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function OrchestratorPanel({
  orchestrator,
}: {
  orchestrator: ReturnType<typeof useOrchestrator>;
}) {
  const { plan, workers, maxWorkers, output, isRunning, error } = orchestrator;

  return (
    <div className="space-y-3">
      <p className="text-[10px] text-muted-foreground">
        Max workers: {maxWorkers}
      </p>

      {isRunning && !plan && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
          Decomposing...
        </div>
      )}

      {error && <p className="text-sm text-red-500">{error}</p>}

      {plan && <SubtaskList subtasks={plan} />}

      {workers.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Workers (concurrent)
          </h3>
          <div className="grid gap-2 sm:grid-cols-2">
            {workers.map((worker) => (
              <PlanStepCard
                key={worker.worker_id}
                step={workerToStep(worker)}
              />
            ))}
          </div>
        </div>
      )}

      {output && (
        <div className="rounded-lg border p-4">
          <h2 className="mb-3 text-sm font-semibold">Final Answer</h2>
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <Markdown>{output}</Markdown>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MultiAgentPanel
// ---------------------------------------------------------------------------

const AGENT_BADGE: Record<string, string> = {
  researcher: "bg-blue-100 text-blue-700",
  analyst: "bg-amber-100 text-amber-700",
  writer: "bg-purple-100 text-purple-700",
};

function MultiAgentStepCard({ step }: { step: MultiAgentStepState }) {
  const [inputExpanded, setInputExpanded] = useState(false);
  const [toolsExpanded, setToolsExpanded] = useState(false);
  const borderClass =
    step.status === "error"
      ? "border-red-500"
      : step.status === "done"
        ? "border-green-500"
        : step.status === "running"
          ? "border-blue-500"
          : "border-border";

  return (
    <div className={cn("rounded-lg border-2 p-3", borderClass)}>
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "rounded px-2 py-0.5 text-[10px] font-semibold",
            AGENT_BADGE[step.agent_id] ?? "bg-muted text-muted-foreground",
          )}
        >
          {step.label}
        </span>
        {step.status === "running" && (
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        )}
      </div>

      {step.input && (
        <div className="mt-2 border-t pt-2">
          <button
            className="flex w-full items-center gap-1 text-left text-xs font-medium text-muted-foreground hover:text-foreground"
            onClick={() => setInputExpanded(!inputExpanded)}
          >
            <span>{inputExpanded ? "▾" : "▸"}</span>
            <span>Input (handoff)</span>
          </button>
          {inputExpanded && (
            <pre className="mt-1 max-h-32 overflow-y-auto rounded bg-muted p-2 text-xs break-words whitespace-pre-wrap">
              {step.input}
            </pre>
          )}
        </div>
      )}

      {step.tool_calls && step.tool_calls.length > 0 && (
        <div className="mt-2 border-t pt-2">
          <button
            className="flex w-full items-center gap-1 text-left text-xs font-medium text-muted-foreground hover:text-foreground"
            onClick={() => setToolsExpanded(!toolsExpanded)}
          >
            <span>{toolsExpanded ? "▾" : "▸"}</span>
            <span>Tool calls ({step.tool_calls.length})</span>
          </button>
          {toolsExpanded && (
            <div className="mt-1 space-y-2">
              {step.tool_calls.map((call, i) => (
                <div key={i}>
                  <p className="font-mono text-xs">
                    {call.tool}({call.args ? JSON.stringify(call.args) : ""})
                  </p>
                  {call.observation && (
                    <pre className="mt-1 max-h-32 overflow-y-auto rounded bg-muted p-2 text-xs break-words whitespace-pre-wrap">
                      {call.observation}
                    </pre>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {step.status === "error" ? (
        <p className="mt-2 text-xs text-red-500">{step.error}</p>
      ) : (
        step.output && (
          <div className="mt-2 border-t pt-2">
            <span className="text-xs font-semibold text-muted-foreground">
              Output
            </span>
            <div className="prose prose-sm max-w-none dark:prose-invert">
              <Markdown>{step.output}</Markdown>
            </div>
          </div>
        )
      )}
    </div>
  );
}

function RosterList({
  agents,
  reason,
}: {
  agents: string[];
  reason: string | null;
}) {
  return (
    <div className="rounded-lg border p-3">
      <span className="text-xs font-semibold text-muted-foreground">
        Roster
      </span>
      <ol className="mt-1 flex flex-wrap items-center gap-2">
        {agents.map((a, i) => (
          <li key={a} className="flex items-center gap-2 text-sm">
            <span className="text-xs font-semibold text-muted-foreground">
              {i + 1}.
            </span>
            <span className="capitalize">{a}</span>
            {i < agents.length - 1 && (
              <span className="text-muted-foreground">-&gt;</span>
            )}
          </li>
        ))}
      </ol>
      {reason && (
        <p className="mt-1 text-xs text-muted-foreground italic">{reason}</p>
      )}
    </div>
  );
}

function MultiAgentPanel({
  multiAgent,
}: {
  multiAgent: ReturnType<typeof useMultiAgent>;
}) {
  const { agents, reason, steps, maxTools, output, isRunning, error } =
    multiAgent;

  return (
    <div className="space-y-3">
      <p className="text-[10px] text-muted-foreground">
        Researcher tool budget: {maxTools}
      </p>

      {isRunning && !agents && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
          Routing the roster...
        </div>
      )}

      {error && <p className="text-sm text-red-500">{error}</p>}

      {agents && <RosterList agents={agents} reason={reason} />}

      {steps.length > 0 && (
        <div className="flex flex-col gap-2">
          <span className="text-xs font-semibold text-muted-foreground">
            Pipeline (sequential)
          </span>
          {steps.map((step, i) => (
            <div key={`${step.order}-${step.agent_id}`}>
              <MultiAgentStepCard step={step} />
              {i < steps.length - 1 && (
                <div className="flex justify-center py-1">
                  <span className="text-sm text-muted-foreground">↓</span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {output && (
        <div className="rounded-lg border p-4">
          <h2 className="mb-3 text-sm font-semibold">Final Answer</h2>
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <Markdown>{output}</Markdown>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// DagPanel
// ---------------------------------------------------------------------------

function DagNodeCard({ node }: { node: DagNodeState }) {
  const [toolExpanded, setToolExpanded] = useState(false);
  const borderClass =
    node.status === "error"
      ? "border-red-500"
      : node.status === "done"
        ? "border-green-500"
        : node.status === "running"
          ? "border-blue-500"
          : "border-border";

  return (
    <div
      className={cn(
        "min-w-[180px] flex-1 rounded-lg border-2 p-3",
        borderClass,
      )}
    >
      <div className="flex items-center gap-2">
        <span className="rounded bg-muted px-2 py-0.5 font-mono text-[10px] font-semibold">
          {node.node_id}
        </span>
        <span className="text-xs font-semibold">{node.label}</span>
        {node.status === "running" && (
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        )}
      </div>

      {node.depends_on.length > 0 && (
        <p className="mt-1 font-mono text-[10px] text-muted-foreground">
          &lt;- {node.depends_on.join(", ")}
        </p>
      )}

      {node.tool && (
        <div className="mt-2 border-t pt-2">
          <button
            className="flex w-full items-center gap-1 text-left text-xs font-medium text-muted-foreground hover:text-foreground"
            onClick={() => setToolExpanded(!toolExpanded)}
          >
            <span>{toolExpanded ? "▾" : "▸"}</span>
            <span className="font-mono">
              {node.tool}({node.tool_args ? JSON.stringify(node.tool_args) : ""})
            </span>
          </button>
          {toolExpanded && node.observation && (
            <pre className="mt-1 max-h-32 overflow-y-auto rounded bg-muted p-2 text-xs break-words whitespace-pre-wrap">
              {node.observation}
            </pre>
          )}
        </div>
      )}

      {node.status === "error" ? (
        <p className="mt-2 text-xs text-red-500">{node.error}</p>
      ) : (
        node.output && (
          <div className="mt-2 border-t pt-2">
            <div className="prose prose-sm max-w-none dark:prose-invert">
              <Markdown>{node.output}</Markdown>
            </div>
          </div>
        )
      )}
    </div>
  );
}

function DagPanel({ dag }: { dag: ReturnType<typeof useDag> }) {
  const { nodes, waves, maxNodes, output, isRunning, error } = dag;

  return (
    <div className="space-y-3">
      <p className="text-[10px] text-muted-foreground">
        Graph node budget: {maxNodes}
      </p>

      {isRunning && !waves && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
          Decomposing into a graph...
        </div>
      )}

      {error && <p className="text-sm text-red-500">{error}</p>}

      {waves && (
        <p className="text-xs font-semibold text-muted-foreground">
          {nodes.length} nodes, {waves.length} waves
        </p>
      )}

      {waves && (
        <div className="flex flex-col gap-2">
          {waves.map((wave, w) => (
            <div key={w}>
              <span className="text-[10px] font-semibold text-muted-foreground">
                Wave {w}
              </span>
              <div className="mt-1 flex flex-wrap gap-2">
                {wave.map((nodeId) => {
                  const node = nodes.find((n) => n.node_id === nodeId);
                  return node ? <DagNodeCard key={nodeId} node={node} /> : null;
                })}
              </div>
              {w < waves.length - 1 && (
                <div className="flex justify-center py-1">
                  <span className="text-sm text-muted-foreground">↓</span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {output && (
        <div className="rounded-lg border p-4">
          <h2 className="mb-3 text-sm font-semibold">Final Answer</h2>
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <Markdown>{output}</Markdown>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// AutonomousPanel
// ---------------------------------------------------------------------------

const STOP_REASON_LABEL: Record<string, string> = {
  complete: "Goal complete",
  no_progress: "Stopped: no progress",
  budget: "Stopped: cycle budget reached",
  error: "Stopped: error",
};

function AutonomousCycleCard({ cycle }: { cycle: AutonomousCycleState }) {
  const [toolExpanded, setToolExpanded] = useState(false);
  const borderClass =
    cycle.status === "error"
      ? "border-red-500"
      : cycle.status === "done"
        ? "border-green-500"
        : cycle.status === "running"
          ? "border-blue-500"
          : "border-border";

  const actionLabel = cycle.spawned ? "subagent" : cycle.action;

  return (
    <div className={cn("rounded-lg border-2 p-3", borderClass)}>
      <div className="flex items-center gap-2">
        <span className="rounded bg-muted px-2 py-0.5 font-mono text-[10px] font-semibold">
          #{cycle.index}
        </span>
        <span className="rounded bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase">
          {actionLabel}
        </span>
        {cycle.goal_complete && (
          <span className="rounded bg-green-500/15 px-2 py-0.5 text-[10px] font-semibold text-green-600">
            goal complete
          </span>
        )}
        {cycle.status === "running" && (
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        )}
      </div>

      {cycle.reflection && (
        <p className="mt-2 text-xs text-muted-foreground italic">
          {cycle.reflection}
        </p>
      )}

      {cycle.task && (
        <p className="mt-2 text-xs font-medium">Task: {cycle.task}</p>
      )}

      {cycle.tool && (
        <div className="mt-2 border-t pt-2">
          <button
            className="flex w-full items-center gap-1 text-left text-xs font-medium text-muted-foreground hover:text-foreground"
            onClick={() => setToolExpanded(!toolExpanded)}
          >
            <span>{toolExpanded ? "▾" : "▸"}</span>
            <span className="font-mono">
              {cycle.tool}({cycle.tool_args ? JSON.stringify(cycle.tool_args) : ""})
            </span>
          </button>
          {toolExpanded && cycle.observation && (
            <pre className="mt-1 max-h-32 overflow-y-auto rounded bg-muted p-2 text-xs break-words whitespace-pre-wrap">
              {cycle.observation}
            </pre>
          )}
        </div>
      )}

      {cycle.subagent_steps && cycle.subagent_steps.length > 0 && (
        <div className="mt-2 border-t pt-2">
          <p className="text-[10px] font-semibold text-muted-foreground">
            Sub-agent ({cycle.subagent_steps.length} tool
            {cycle.subagent_steps.length > 1 ? "s" : ""})
          </p>
          <ul className="mt-1 space-y-0.5">
            {cycle.subagent_steps.map((step, i) => (
              <li
                key={i}
                className="font-mono text-[10px] text-muted-foreground"
              >
                {step.tool}({step.args ? JSON.stringify(step.args) : ""})
              </li>
            ))}
          </ul>
        </div>
      )}

      {cycle.status === "error" ? (
        <p className="mt-2 text-xs text-red-500">{cycle.error}</p>
      ) : (
        cycle.output && (
          <div className="mt-2 border-t pt-2">
            <div className="prose prose-sm max-w-none dark:prose-invert">
              <Markdown>{cycle.output}</Markdown>
            </div>
          </div>
        )
      )}
    </div>
  );
}

function AutonomousPanel({
  autonomous,
}: {
  autonomous: ReturnType<typeof useAutonomous>;
}) {
  const {
    goal,
    backlog,
    cycles,
    maxCycles,
    stopReason,
    output,
    isRunning,
    error,
  } = autonomous;

  return (
    <div className="space-y-3">
      <p className="text-[10px] text-muted-foreground">
        Cycle budget: {maxCycles}
      </p>

      {isRunning && !goal && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
          Setting the goal...
        </div>
      )}

      {error && <p className="text-sm text-red-500">{error}</p>}

      {goal && (
        <div className="rounded-lg border p-3">
          <span className="text-[10px] font-semibold text-muted-foreground uppercase">
            Goal
          </span>
          <p className="mt-1 text-sm font-medium">{goal}</p>
          {backlog.length > 0 && (
            <ul className="mt-2 list-disc space-y-0.5 pl-4">
              {backlog.map((task, i) => (
                <li key={i} className="text-xs text-muted-foreground">
                  {task}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {cycles.length > 0 && (
        <div className="flex flex-col gap-2">
          {cycles.map((cycle) => (
            <div key={cycle.index}>
              <AutonomousCycleCard cycle={cycle} />
              {cycle.index < cycles.length - 1 && (
                <div className="flex justify-center py-1">
                  <span className="text-sm text-muted-foreground">↓</span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {stopReason && STOP_REASON_LABEL[stopReason] && (
        <p className="text-xs font-semibold text-muted-foreground">
          {STOP_REASON_LABEL[stopReason]}
        </p>
      )}

      {output && (
        <div className="rounded-lg border p-4">
          <h2 className="mb-3 text-sm font-semibold">Final Answer</h2>
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <Markdown>{output}</Markdown>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Compare — AgentTypeSelect + AgentColumn
// ---------------------------------------------------------------------------

function chainStatusFromSteps(
  steps: ChainStepState[],
  isRunning: boolean,
): RunStatus {
  if (isRunning) return "running";
  if (steps.some((s) => s.status === "error")) return "error";
  const format = steps.find((s) => s.step_id === "format");
  if (format?.status === "done") return "done";
  return "idle";
}

function AgentTypeSelect({
  value,
  onChange,
  exclude,
  disabled,
}: {
  value: ComparableAgentType;
  onChange: (t: ComparableAgentType) => void;
  exclude: ComparableAgentType[];
  disabled: boolean;
}) {
  const options = COMPARABLE_TYPES.filter(
    (t) => t === value || !exclude.includes(t),
  );
  return (
    <select
      className="rounded-md border px-2 py-1 text-sm font-medium"
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value as ComparableAgentType)}
    >
      {options.map((t) => (
        <option key={t} value={t}>
          {AGENT_REGISTRY[t].label}
        </option>
      ))}
    </select>
  );
}

function AgentColumn({
  controller,
  query,
  hasActivity,
  onChangeType,
  onStop,
  exclude,
  disabled,
}: {
  controller: AgentController;
  query: string;
  hasActivity: boolean;
  onChangeType: (t: ComparableAgentType) => void;
  onStop: () => void;
  exclude: ComparableAgentType[];
  disabled: boolean;
}) {
  const autoElapsed = useElapsed(controller.isRunning);
  const elapsed = controller.elapsedMs ?? autoElapsed;

  return (
    <div className="space-y-2 rounded-lg border p-3">
      <div className="flex items-center justify-between gap-2">
        <AgentTypeSelect
          value={controller.type}
          onChange={onChangeType}
          exclude={exclude}
          disabled={disabled}
        />
        <div className="flex items-center gap-1">
          {elapsed !== null && (
            <span className="text-xs text-muted-foreground">
              {(elapsed / 1000).toFixed(1)}s
            </span>
          )}
          <StatusBadge status={controller.status} />
          {controller.status === "running" && (
            <Button
              type="button"
              variant="destructive"
              size="sm"
              className="h-6 px-2 py-0 text-xs"
              onClick={onStop}
            >
              Stop
            </Button>
          )}
        </div>
      </div>
      <p className="text-[11px] text-muted-foreground">
        {AGENT_REGISTRY[controller.type].blurb}
      </p>
      {controller.status === "idle" && !hasActivity && (
        <p className="rounded-md border border-dashed px-3 py-2 text-center text-xs text-muted-foreground">
          Press Run to start.
        </p>
      )}
      {controller.renderProcess(query)}
      {controller.renderResult()}
    </div>
  );
}

// ---------------------------------------------------------------------------
// HistoryRow
// ---------------------------------------------------------------------------

const HISTORY_BADGE: Record<HistoryRunSummary["status"], string> = {
  done: "text-green-600 bg-green-50",
  running: "text-blue-600 bg-blue-50",
  error: "text-red-600 bg-red-50",
  stopped: "text-amber-600 bg-amber-50",
};

function HistoryRow({
  run,
  isActive,
  onClick,
  onStop,
}: {
  run: HistoryRunSummary;
  isActive: boolean;
  onClick: () => void;
  onStop?: () => void;
}) {
  return (
    <div
      className={cn(
        "group/row rounded-md transition-colors hover:bg-muted",
        isActive && "bg-muted",
      )}
    >
      <button className="w-full px-3 py-2 text-left text-sm" onClick={onClick}>
        <div className="flex items-center justify-between gap-2">
          <span className="flex-1 truncate text-xs">{run.query}</span>
          <span
            className={cn(
              "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium",
              HISTORY_BADGE[run.status],
            )}
          >
            {run.status}
          </span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
            {AGENT_REGISTRY[run.type].label}
          </span>
          <span className="text-[10px] text-muted-foreground">
            {new Date(run.created_at).toLocaleString()}
          </span>
        </div>
      </button>
      {run.status === "running" && onStop && (
        <div className="px-3 pb-2">
          <button
            type="button"
            className="text-[10px] font-medium text-destructive hover:underline"
            onClick={onStop}
          >
            Stop
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// HistorySidebar — docked left panel, open by default
// ---------------------------------------------------------------------------

function HistorySidebar({
  onClose,
  runs,
  activeId,
  onSelect,
  onStop,
  isRunning,
}: {
  onClose: () => void;
  runs: HistoryRunSummary[];
  activeId: string | null;
  onSelect: (run: HistoryRunSummary) => void;
  onStop: (run: HistoryRunSummary) => void;
  isRunning: boolean;
}) {
  return (
    <aside className="hidden w-72 shrink-0 self-start rounded-lg border md:block">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h2 className="text-sm font-semibold">History ({runs.length})</h2>
        <button
          className="text-lg leading-none text-muted-foreground hover:text-foreground"
          onClick={onClose}
          aria-label="Collapse history"
        >
          &times;
        </button>
      </div>
      <div className="max-h-[calc(100vh-12rem)] space-y-1 overflow-y-auto p-2">
        {runs.length === 0 ? (
          <p className="px-3 py-2 text-xs text-muted-foreground">
            No runs yet.
          </p>
        ) : (
          runs.map((r) => (
            <HistoryRow
              key={r.id}
              run={r}
              isActive={r.id === activeId}
              onClick={() => {
                if (!isRunning) onSelect(r);
              }}
              onStop={() => onStop(r)}
            />
          ))
        )}
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// AgentsPage
// ---------------------------------------------------------------------------

function AgentsPage() {
  const [selectedTypes, setSelectedTypes] = useState<ComparableAgentType[]>([
    "chain",
  ]);
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [activeHistoryId, setActiveHistoryId] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Workflow type -> run id for runs being polled to completion after a reload
  // or after the user pressed Stop (whose persisted detail we keep refreshing
  // until it reaches a terminal status).
  const [reconnectRuns, setReconnectRuns] = useState<
    Partial<Record<ComparableAgentType, string>>
  >({});
  // The saved workspace, read once synchronously so the persist effect can tell
  // a fresh mount from a restored one (and not clobber the saved session).
  const savedSessionRef = useRef<AgentsSession | null>(loadAgentsSession());
  const hydratedRef = useRef(false);
  const [parallelStrategy, setParallelStrategy] =
    useState<ParallelStrategy>("sectioning");
  const [parallelN, setParallelN] = useState(3);
  const [planAllowReplan] = useState(true);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Agent iteration caps / thresholds are omitted from the request: the backend falls
  // back to the LLMSettings singleton, and each agent hook mirrors that same singleton
  // into its panel header. Source of truth stays in one place (the singleton).

  const queryClient = useQueryClient();

  const { data: models = [] } = useQuery({
    queryKey: queryKeys.llm.models(),
    queryFn: fetchModels,
    retry: false,
  });

  const { data: historyRuns = [] } = useQuery({
    queryKey: queryKeys.llm.allRuns(),
    queryFn: fetchAllRuns,
    retry: false,
  });

  const chain = usePromptChain();
  const single = useSinglePrompt();
  const routing = useRouting();
  const parallel = useParallel();
  const react = useReact();
  const evaluate = useEvaluate();
  const planExec = usePlanExecute();
  const orchestrator = useOrchestrator();
  const multiAgent = useMultiAgent();
  const dag = useDag();
  const autonomous = useAutonomous();

  useEffect(() => {
    if (models.length > 0 && !selectedModel) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- default the model picker once models load
      setSelectedModel(models[0].name);
    }
  }, [models, selectedModel]);

  const routingRunning = routing.isClassifying || routing.isExecuting;
  const isRunning =
    Object.keys(reconnectRuns).length > 0 ||
    chain.isRunning ||
    single.isRunning ||
    routingRunning ||
    parallel.isRunning ||
    react.isRunning ||
    evaluate.isRunning ||
    planExec.isRunning ||
    orchestrator.isRunning ||
    multiAgent.isRunning ||
    dag.isRunning ||
    autonomous.isRunning;

  // The latest persisted run id per workflow type, mirrored from each hook.
  // Single prompt is ephemeral (not persisted) so it has no run id.
  const liveRunIds: Partial<Record<ComparableAgentType, string>> = {
    chain: chain.runId ?? undefined,
    route: routing.runId ?? undefined,
    parallel: parallel.runId ?? undefined,
    react: react.runId ?? undefined,
    evaluate: evaluate.runId ?? undefined,
    plan: planExec.runId ?? undefined,
    orchestrate: orchestrator.runId ?? undefined,
    multiagent: multiAgent.runId ?? undefined,
    dag: dag.runId ?? undefined,
    autonomous: autonomous.runId ?? undefined,
  };

  // Restore the workspace once on mount and reconnect to any still-running runs.
  // The backend keeps executing a workflow after the client disconnects, so a
  // reload just re-reads the persisted runs and polls the running ones to done.
  useEffect(() => {
    const session = savedSessionRef.current;
    if (!session) {
      hydratedRef.current = true;
      return;
    }
    setSelectedTypes(session.selectedTypes);
    setActiveQuery(session.query);

    let cancelled = false;
    (async () => {
      const stillRunning: Partial<Record<ComparableAgentType, string>> = {};
      for (const [type, id] of Object.entries(session.runs) as [
        ComparableAgentType,
        string,
      ][]) {
        try {
          const status = await applyRunDetail(type, id);
          if (status === "running") stillRunning[type] = id;
        } catch {
          // Run no longer exists (pruned/expired) — drop it.
        }
      }
      if (!cancelled) setReconnectRuns(stillRunning);
      hydratedRef.current = true;
    })();

    return () => {
      cancelled = true;
    };
    // Mount-only: restore the saved session exactly once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist the workspace whenever it changes (after the initial hydration, so
  // the first renders never overwrite the session we are about to restore).
  useEffect(() => {
    if (!hydratedRef.current) return;
    const runs: Partial<Record<ComparableAgentType, string>> = {};
    for (const t of selectedTypes) {
      const id = liveRunIds[t];
      if (id) runs[t] = id;
    }
    saveAgentsSession({ selectedTypes, query: activeQuery, runs });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    selectedTypes,
    activeQuery,
    chain.runId,
    routing.runId,
    parallel.runId,
    react.runId,
    evaluate.runId,
    planExec.runId,
    orchestrator.runId,
    multiAgent.runId,
    dag.runId,
    autonomous.runId,
  ]);

  // Poll the persisted detail of each reconnecting run until it reaches a
  // terminal status, rehydrating the panel on every tick.
  useEffect(() => {
    if (Object.keys(reconnectRuns).length === 0) return;
    let cancelled = false;
    const interval = setInterval(() => {
      void (async () => {
        for (const [type, id] of Object.entries(reconnectRuns) as [
          ComparableAgentType,
          string,
        ][]) {
          try {
            const status = await applyRunDetail(type, id);
            if (!cancelled && status !== "running") {
              setReconnectRuns((prev) => {
                const next = { ...prev };
                delete next[type];
                return next;
              });
            }
          } catch {
            // Transient fetch error — try again on the next tick.
          }
        }
      })();
    }, 1500);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reconnectRuns]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim() || isRunning) return;
    setActiveHistoryId(null);
    setReconnectRuns({});
    setActiveQuery(query.trim());
    const model = selectedModel || undefined;
    const q = query.trim();
    selectedTypes.forEach((t) => makeController(t).run(q, model));
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && e.ctrlKey) {
      e.preventDefault();
      handleSubmit(e as unknown as React.FormEvent);
    }
  }

  // Fetch a persisted run's detail and rehydrate the matching workflow hook.
  // Returns the run's status ("running" | "done" | "error") so callers can poll
  // running runs, or null for types that are not persisted (single prompt).
  async function applyRunDetail(
    type: ComparableAgentType,
    id: string,
  ): Promise<string | null> {
    switch (type) {
      case "chain": {
        const d = await fetchChainRunDetail(id);
        chain.loadFromDetail(d);
        return d.status;
      }
      case "route": {
        const d = await fetchRouteRunDetail(id);
        routing.loadFromDetail(d);
        return d.status;
      }
      case "parallel": {
        const d = await fetchParallelRunDetail(id);
        parallel.loadFromDetail(d);
        return d.status;
      }
      case "react": {
        const d = await fetchReactRunDetail(id);
        react.loadFromDetail(d);
        return d.status;
      }
      case "evaluate": {
        const d = await fetchEvalOptRunDetail(id);
        evaluate.loadFromDetail(d);
        return d.status;
      }
      case "plan": {
        const d = await fetchPlanRunDetail(id);
        planExec.loadFromDetail(d);
        return d.status;
      }
      case "orchestrate": {
        const d = await fetchOrchestratorRunDetail(id);
        orchestrator.loadFromDetail(d);
        return d.status;
      }
      case "multiagent": {
        const d = await fetchMultiAgentRunDetail(id);
        multiAgent.loadFromDetail(d);
        return d.status;
      }
      case "dag": {
        const d = await fetchDagRunDetail(id);
        dag.loadFromDetail(d);
        return d.status;
      }
      case "autonomous": {
        const d = await fetchAutonomousRunDetail(id);
        autonomous.loadFromDetail(d);
        return d.status;
      }
      default:
        return null;
    }
  }

  async function handleHistorySelect(run: HistoryRunSummary) {
    if (isRunning) return;
    setActiveHistoryId(run.id);
    setReconnectRuns({});
    // Replace the workspace with a single panel of the run's type, then rehydrate
    // that workflow's hook from its persisted detail.
    setSelectedTypes([run.type]);
    setActiveQuery(run.query);
    setQuery(run.query);
    await applyRunDetail(run.type, run.id);
  }

  function handleReset() {
    chain.reset();
    single.reset();
    routing.reset();
    parallel.reset();
    react.reset();
    evaluate.reset();
    planExec.reset();
    orchestrator.reset();
    multiAgent.reset();
    dag.reset();
    autonomous.reset();
    setReconnectRuns({});
    setActiveQuery("");
  }

  // Stop running workflows: cancel them on the backend, drop the live stream,
  // then poll their persisted detail so the panel settles on the stopped state.
  // With no argument, stops every currently-running workflow (and any run still
  // executing on the backend that we reconnected to after a reload).
  async function handleStop(only?: ComparableAgentType) {
    const targets: Partial<Record<ComparableAgentType, string>> = {};
    for (const [type, id] of Object.entries(reconnectRuns) as [
      ComparableAgentType,
      string,
    ][]) {
      if (only && type !== only) continue;
      targets[type] = id;
    }
    for (const { type, controller } of panels) {
      if (only && type !== only) continue;
      const id = liveRunIds[type];
      if (controller.status === "running" && id) targets[type] = id;
    }
    const entries = Object.entries(targets) as [ComparableAgentType, string][];
    if (entries.length === 0) return;

    setReconnectRuns((prev) => ({ ...prev, ...targets }));
    await Promise.all(
      entries.map(async ([type, id]) => {
        try {
          await cancelRun(type as HistoryAgentType, id);
        } catch {
          // Best effort: the poll below still reflects whatever the backend does.
        }
        // Drop the now-doomed live stream; the poll repaints from the DB.
        makeController(type).reset();
      }),
    );
  }

  // Stop a run picked from the history list. If it is the run currently shown in
  // a panel, route through handleStop (which resets the live stream + reconnects);
  // otherwise just cancel it and refresh the list.
  async function handleStopRun(run: HistoryRunSummary) {
    if (liveRunIds[run.type] === run.id) {
      await handleStop(run.type);
      return;
    }
    try {
      await cancelRun(run.type, run.id);
    } catch {
      // Best effort.
    }
    queryClient.invalidateQueries({ queryKey: queryKeys.llm.allRuns() });
  }

  function makeController(type: ComparableAgentType): AgentController {
    if (type === "single") {
      return {
        type,
        run: single.run,
        reset: single.reset,
        isRunning: single.isRunning,
        elapsedMs: single.elapsedMs,
        status: single.isRunning
          ? "running"
          : single.error
            ? "error"
            : single.result
              ? "done"
              : "idle",
        renderProcess: () => (
          <p className="text-xs text-muted-foreground">
            Direct answer - no intermediate steps.
          </p>
        ),
        renderResult: () => (
          <SinglePromptPanel
            result={single.result}
            isRunning={single.isRunning}
            elapsedMs={single.elapsedMs}
            error={single.error}
          />
        ),
      };
    }
    if (type === "chain") {
      return {
        type,
        run: chain.run,
        reset: chain.reset,
        isRunning: chain.isRunning,
        status: chainStatusFromSteps(chain.steps, chain.isRunning),
        renderProcess: (q) => (
          <ChainPanel steps={chain.steps} runId={chain.runId} query={q} />
        ),
        renderResult: () => null,
      };
    }
    if (type === "parallel") {
      return {
        type,
        run: (q, model) =>
          parallel.run(q, model, { strategy: parallelStrategy, n: parallelN }),
        reset: parallel.reset,
        isRunning: parallel.isRunning,
        status: parallel.isRunning
          ? "running"
          : parallel.error
            ? "error"
            : parallel.output
              ? "done"
              : "idle",
        renderProcess: () => (
          <ParallelPanel
            parallel={parallel}
            controls={{
              strategy: parallelStrategy,
              n: parallelN,
              onStrategyChange: setParallelStrategy,
              onNChange: setParallelN,
              disabled: isRunning,
            }}
          />
        ),
        renderResult: () => null,
      };
    }
    if (type === "react") {
      return {
        type,
        run: (q, model) => react.run(q, model),
        reset: react.reset,
        isRunning: react.isRunning,
        status: react.isRunning
          ? "running"
          : react.error
            ? "error"
            : react.output
              ? "done"
              : "idle",
        renderProcess: () => <ReactPanel react={react} />,
        renderResult: () => null,
      };
    }
    if (type === "evaluate") {
      return {
        type,
        run: (q, model) => evaluate.run(q, model),
        reset: evaluate.reset,
        isRunning: evaluate.isRunning,
        status: evaluate.isRunning
          ? "running"
          : evaluate.error
            ? "error"
            : evaluate.output
              ? "done"
              : "idle",
        renderProcess: () => <EvaluatePanel evaluate={evaluate} />,
        renderResult: () => null,
      };
    }
    if (type === "plan") {
      return {
        type,
        run: (q, model) =>
          planExec.run(q, model, { allowReplan: planAllowReplan }),
        reset: planExec.reset,
        isRunning: planExec.isRunning,
        status: planExec.isRunning
          ? "running"
          : planExec.error
            ? "error"
            : planExec.output
              ? "done"
              : "idle",
        renderProcess: () => <PlanExecutePanel planExec={planExec} />,
        renderResult: () => null,
      };
    }
    if (type === "orchestrate") {
      return {
        type,
        run: (q, model) => orchestrator.run(q, model),
        reset: orchestrator.reset,
        isRunning: orchestrator.isRunning,
        status: orchestrator.isRunning
          ? "running"
          : orchestrator.error
            ? "error"
            : orchestrator.output
              ? "done"
              : "idle",
        renderProcess: () => <OrchestratorPanel orchestrator={orchestrator} />,
        renderResult: () => null,
      };
    }
    if (type === "multiagent") {
      return {
        type,
        run: (q, model) => multiAgent.run(q, model),
        reset: multiAgent.reset,
        isRunning: multiAgent.isRunning,
        status: multiAgent.isRunning
          ? "running"
          : multiAgent.error
            ? "error"
            : multiAgent.output
              ? "done"
              : "idle",
        renderProcess: () => <MultiAgentPanel multiAgent={multiAgent} />,
        renderResult: () => null,
      };
    }
    if (type === "dag") {
      return {
        type,
        run: (q, model) => dag.run(q, model),
        reset: dag.reset,
        isRunning: dag.isRunning,
        status: dag.isRunning
          ? "running"
          : dag.error
            ? "error"
            : dag.output
              ? "done"
              : "idle",
        renderProcess: () => <DagPanel dag={dag} />,
        renderResult: () => null,
      };
    }
    if (type === "autonomous") {
      return {
        type,
        run: (q, model) => autonomous.run(q, model),
        reset: autonomous.reset,
        isRunning: autonomous.isRunning,
        status: autonomous.isRunning
          ? "running"
          : autonomous.error
            ? "error"
            : autonomous.output
              ? "done"
              : "idle",
        renderProcess: () => <AutonomousPanel autonomous={autonomous} />,
        renderResult: () => null,
      };
    }
    return {
      type,
      run: routing.run,
      reset: routing.reset,
      isRunning: routingRunning,
      status: routingRunning
        ? "running"
        : routing.error
          ? "error"
          : routing.output
            ? "done"
            : "idle",
      renderProcess: (q) => <RoutingPanel routing={routing} query={q} />,
      renderResult: () => null,
    };
  }

  function addType() {
    const next = COMPARABLE_TYPES.find((t) => !selectedTypes.includes(t));
    if (next) setSelectedTypes((prev) => [...prev, next]);
  }

  function removeType(t: ComparableAgentType) {
    if (selectedTypes.length <= 1) return;
    makeController(t).reset();
    setSelectedTypes((prev) => prev.filter((x) => x !== t));
  }

  function changeType(index: number, next: ComparableAgentType) {
    const current = selectedTypes[index];
    if (current === next || selectedTypes.includes(next)) return;
    makeController(current).reset();
    setSelectedTypes((prev) => prev.map((t, i) => (i === index ? next : t)));
  }

  const canAdd = selectedTypes.length < COMPARABLE_TYPES.length;

  // Build each panel's controller once and reuse it for the chip row, the
  // aggregate status line, and the grid.
  const panels = selectedTypes.map((type, index) => ({
    type,
    index,
    controller: makeController(type),
  }));
  const doneCount = panels.filter((p) => p.controller.status === "done").length;
  const runningCount = panels.filter(
    (p) => p.controller.status === "running",
  ).length;
  const errorCount = panels.filter(
    (p) => p.controller.status === "error",
  ).length;
  const anyActivity = doneCount + runningCount + errorCount > 0;

  return (
    <AppShell>
      <SettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />
      <div className="flex gap-4">
        {historyOpen && (
          <HistorySidebar
            onClose={() => setHistoryOpen(false)}
            runs={historyRuns}
            activeId={activeHistoryId}
            onSelect={handleHistorySelect}
            onStop={handleStopRun}
            isRunning={isRunning}
          />
        )}
        <div className="min-w-0 flex-1 space-y-4">
          {/* Header */}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-xl font-semibold">Agents</h1>
              {/* Chat left this page in issue #8 - the two workspaces have genuinely
                  different shapes - but they stay one click apart. */}
              <WorkspaceSwitch active="/agents" />
              <p className="text-sm text-muted-foreground">
                Run one query across {selectedTypes.length} workflow
                {selectedTypes.length === 1 ? "" : "s"}.
              </p>
            </div>
            <div className="flex items-center gap-2">
              {models.length > 0 && (
                <select
                  className="rounded-md border px-2 py-1 text-sm"
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                >
                  {models.map((m) => (
                    <option key={m.name} value={m.name}>
                      {m.name}
                    </option>
                  ))}
                </select>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={() => setHistoryOpen((o) => !o)}
              >
                {historyOpen ? "Hide" : "History"}
                {!historyOpen && historyRuns.length > 0
                  ? ` (${historyRuns.length})`
                  : ""}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setSettingsOpen(true)}
                aria-label="Settings"
              >
                Settings
              </Button>
            </div>
          </div>

          <div className="space-y-4">
            {/* Query form */}
            <form onSubmit={handleSubmit} className="flex gap-2">
              <textarea
                ref={textareaRef}
                className="flex-1 resize-none rounded-md border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                rows={2}
                placeholder={PLACEHOLDERS[0]}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isRunning}
              />
              <div className="flex flex-col gap-1">
                <Button
                  type="submit"
                  disabled={isRunning || !query.trim()}
                  size="sm"
                >
                  {isRunning ? "Running…" : "Run"}
                </Button>
                {isRunning ? (
                  <Button
                    type="button"
                    variant="destructive"
                    size="sm"
                    onClick={() => handleStop()}
                  >
                    Stop
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={handleReset}
                  >
                    Reset
                  </Button>
                )}
              </div>
            </form>

            {/* Workflow toolbar - chip summary + aggregate status + add */}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-muted-foreground uppercase">
                  Workflows ({selectedTypes.length})
                </span>
                {panels.map(({ type, controller }) => (
                  <WorkflowChip
                    key={type}
                    label={AGENT_REGISTRY[type].label}
                    status={controller.status}
                    onRemove={
                      selectedTypes.length > 1 && !isRunning
                        ? () => removeType(type)
                        : undefined
                    }
                  />
                ))}
              </div>
              <div className="flex items-center gap-3">
                {anyActivity && (
                  <span className="text-xs text-muted-foreground">
                    {doneCount > 0 && `${doneCount} done`}
                    {runningCount > 0 &&
                      `${doneCount > 0 ? " · " : ""}${runningCount} running`}
                    {errorCount > 0 &&
                      `${doneCount > 0 || runningCount > 0 ? " · " : ""}${errorCount} error`}
                  </span>
                )}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={addType}
                  disabled={!canAdd || isRunning}
                >
                  + Add workflow
                </Button>
              </div>
            </div>

            {/* Workflow grid - 1..N panels, one per selected type */}
            <div
              className={cn(
                "grid gap-4",
                selectedTypes.length > 1 && "md:grid-cols-2 xl:grid-cols-3",
              )}
            >
              {panels.map(({ type, index, controller }) => (
                <AgentColumn
                  key={type}
                  controller={controller}
                  query={activeQuery}
                  hasActivity={anyActivity}
                  onChangeType={(next) => changeType(index, next)}
                  onStop={() => handleStop(type)}
                  exclude={selectedTypes}
                  disabled={isRunning}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
