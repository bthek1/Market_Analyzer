/**
 * The live stream and a refresh-restore must produce the same state (issue #6 phase 2).
 *
 * A step used to be described twice - once by the hand-built SSE payload in the backend
 * workflow module, once by the DRF serializer behind the detail endpoint. Six of the nine
 * workflows disagreed. Whether that was user-visible depended on which name the frontend
 * state type happened to use: `dag` and `autonomous` typed the field as `args`, so
 * `loadFromDetail` - which assigns `detail.steps` straight into state - silently dropped
 * the `tool_args` the server actually sent, and the tool arguments vanished from the UI
 * on every refresh-restore.
 *
 * The same class bit again in issue #7: `react` PERSISTED a step for an unparseable model
 * turn but streamed no event for it, so the live list was one card shorter than the restored
 * one while every card in it matched. Hence the length assertion, and hence react's case
 * carries two steps.
 *
 * CASES is a hand-written literal, so a workflow is only covered once someone adds it -
 * there is no frontend equivalent of `AgentRun.Kind` to derive from. `chat` (issue #8) is
 * covered by `useChatAgent.test.ts` instead of here, because its unit of restore is a
 * SESSION - a conversation containing turns containing steps - so the "select the step list"
 * shape below does not fit it. Same invariant, same mutation checks, different container.
 *
 * Each case below drives a run to completion over SSE, then loads the equivalent detail
 * payload into a fresh hook and asserts the two produce equal state. The step fixtures are
 * written ONCE per workflow and used on both paths, so a case fails if either side is
 * changed alone. Mutation-checked against all three historical shapes: the pre-fix `dag`
 * wire shape, `useBrowserAgent`'s old mapper, and a stream missing react's error step.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { act, waitFor } from "@testing-library/react";
import { renderHookWithQuery } from "@/test/render";
import { useAutonomous } from "@/hooks/useAutonomous";
import { usePromptChain } from "@/hooks/usePromptChain";
import { useBrowserAgent } from "@/hooks/useBrowserAgent";
import { useDag } from "@/hooks/useDag";
import { useEvaluate } from "@/hooks/useEvaluate";
import { useMultiAgent } from "@/hooks/useMultiAgent";
import { useOrchestrator } from "@/hooks/useOrchestrator";
import { useParallel } from "@/hooks/useParallel";
import { usePlanExecute } from "@/hooks/usePlanExecute";
import { useReact } from "@/hooks/useReact";

const RUN_ID = "99999999-9999-9999-9999-999999999999";
const ARGS = { symbol: "AAPL" };
const OBS = '{"trailing_pe": 30}';

function mockFetchSSE(events: object[]) {
  const encoder = new TextEncoder();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: new ReadableStream<Uint8Array>({
        start(controller) {
          for (const evt of events) {
            controller.enqueue(encoder.encode(`data: ${JSON.stringify(evt)}\n\n`));
          }
          controller.close();
        },
      }),
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

/**
 * One workflow's contract. `step` is the row as the backend serialises it - the SSE event
 * is exactly this plus an `event` discriminator, which is the invariant under test.
 */
interface Case {
  name: string;
  hook: () => { run: (q: string) => void; isRunning: boolean; loadFromDetail: (d: never) => void };
  /** The persisted step rows, shared by both paths. */
  steps: Record<string, unknown>[];
  /** SSE events before the step event (plan/started/goal/route...). */
  preamble: object[];
  /** The step event's name. */
  event: string;
  /** The terminal result event. */
  result: object;
  /** The detail payload a refresh-restore would GET. */
  detail: Record<string, unknown>;
  /** Pull the step list out of the hook's return value. */
  select: (state: Record<string, unknown>) => Record<string, unknown>[];
  /** The field the two paths used to disagree about, if any. */
  pinned?: [string, unknown];
}

// An unparseable model turn: persisted with status "error", nudged, and retried. It used
// to be written to the DB without a matching SSE event (issue #7).
const REACT_PARSE_ERROR = {
  id: "row-0",
  order: 0,
  thought: "",
  tool: "",
  tool_args: null,
  observation: "I cannot comply",
  is_answer: false,
  status: "error",
  error: "Could not parse model output as JSON.",
};

const REACT_STEP = {
  id: "row-1",
  order: 1,
  thought: "I need AAPL valuation",
  tool: "company_snapshot",
  tool_args: ARGS,
  observation: OBS,
  is_answer: false,
  status: "done",
  error: null,
};

const PLAN_STEP = {
  id: "row-0",
  order: 0,
  task: "Value AAPL",
  tool: "company_snapshot",
  tool_args: ARGS,
  observation: OBS,
  result: "AAPL trades at 30x.",
  status: "done",
  error: null,
};

const WORKER = {
  id: "row-0",
  worker_id: "valuation",
  label: "valuation",
  task: "Value AAPL",
  order: 0,
  tool: "company_snapshot",
  tool_args: ARGS,
  observation: OBS,
  output: "Above the sector median.",
  status: "done",
  error: null,
};

const DAG_NODE = {
  id: "row-a",
  node_id: "a",
  label: "AAPL",
  task: "value AAPL",
  wave: 0,
  order: 0,
  depends_on: [],
  tool: "company_snapshot",
  tool_args: ARGS,
  observation: OBS,
  output: "AAPL P/E 30.",
  status: "done",
  error: null,
};

const CYCLE = {
  id: "row-0",
  index: 0,
  reflection: "starting out",
  task: "look up AAPL",
  action: "tool",
  tool: "company_snapshot",
  tool_args: ARGS,
  observation: OBS,
  spawned: false,
  subagent_steps: null,
  output: "AAPL trades at 30x.",
  backlog: ["compare to sector"],
  goal_complete: false,
  status: "done",
  error: null,
};

const BROWSER_STEP = {
  id: "row-0",
  order: 0,
  action: "go_to_url",
  action_args: { url: "https://example.test" },
  url: "https://example.test",
  title: "Example",
  evaluation: "found the page",
  memory: "looking for the price",
  screenshot: "",
  output: "open the results page",
  status: "done",
  error: null,
};

const MULTI_STEP = {
  id: "row-0",
  agent_id: "researcher",
  label: "Researcher",
  order: 0,
  input: "is AAPL cheap",
  tool_calls: [{ tool: "company_snapshot", args: ARGS, observation: OBS }],
  output: "AAPL trades at 30x.",
  status: "done",
  error: null,
};

const ITERATION = {
  id: "row-0",
  order: 0,
  draft: "AAPL looks fairly valued.",
  score: 7,
  feedback: "cite the multiple",
  passed: false,
  status: "done",
  error: null,
};

// Chain is the odd one out: its payload carries no `event` discriminator (the frontend
// keys off step_id) and its steps are pre-seeded client-side, so the hook MERGES the event
// into a template rather than appending. It merged only status/output/error, which left
// `id` and the timestamps at the template defaults during a live run - and the chain card
// renders a duration from started_at/completed_at, so the label appeared only after a reload.
const CHAIN_STEP = {
  id: "row-0",
  step_id: "classify",
  label: "Classify Query",
  order: 0,
  status: "done",
  output: '{"intent": "valuation"}',
  error: null,
  started_at: "2026-09-25T04:00:00Z",
  completed_at: "2026-09-25T04:00:02Z",
};

const TASK = {
  id: "row-0",
  task_id: "valuation",
  label: "Valuation",
  order: 0,
  status: "done",
  output: "Above the sector median.",
  vote: null,
  error: null,
};

const CASES: Case[] = [
  {
    name: "chain",
    hook: usePromptChain as never,
    steps: [CHAIN_STEP],
    preamble: [{ run_id: RUN_ID, step_id: "__init__", label: "", status: "running", output: null, error: null }],
    // Chain has no `event` key at all; the harness spreads this name in as a plain field,
    // and `run_id` rides alongside exactly as the backend sends it.
    event: "",
    result: { run_id: RUN_ID, step_id: "__done__", label: "", status: "done", output: null, error: null },
    detail: { id: RUN_ID, steps: [CHAIN_STEP] },
    // Only the step the run actually touched; the other three stay pending in both paths.
    select: (s) =>
      (s.steps as Record<string, unknown>[]).filter((x) => x.step_id === "classify"),
    pinned: ["completed_at", "2026-09-25T04:00:02Z"],
  },
  {
    name: "react",
    hook: useReact as never,
    steps: [REACT_PARSE_ERROR, REACT_STEP],
    preamble: [{ event: "started", max_steps: 6, tools: ["company_snapshot"] }],
    event: "step",
    result: { event: "result", output: "done", run_id: RUN_ID },
    detail: {
      id: RUN_ID,
      steps: [REACT_PARSE_ERROR, REACT_STEP],
      max_steps: 6,
      output: "done",
      error: "",
    },
    select: (s) => s.steps as Record<string, unknown>[],
    pinned: ["tool_args", ARGS],
  },
  {
    name: "plan_exec",
    hook: usePlanExecute as never,
    steps: [PLAN_STEP],
    preamble: [
      { event: "started", max_steps: 6, allow_replan: true },
      { event: "plan", steps: [{ task: "Value AAPL", tool: "company_snapshot", args: ARGS }] },
    ],
    event: "step",
    result: { event: "result", output: "done", steps: 1, replans: 0, run_id: RUN_ID },
    detail: {
      id: RUN_ID,
      plan: [{ task: "Value AAPL", tool: "company_snapshot", args: ARGS }],
      steps: [PLAN_STEP],
      max_steps: 6,
      allow_replan: true,
      replans: 0,
      output: "done",
      error: "",
    },
    select: (s) => s.steps as Record<string, unknown>[],
    pinned: ["tool_args", ARGS],
  },
  {
    name: "orchestrator",
    hook: useOrchestrator as never,
    steps: [WORKER],
    preamble: [
      { event: "started", max_workers: 4 },
      { event: "plan", subtasks: [{ id: "valuation", task: "Value AAPL", focus: "valuation" }] },
    ],
    event: "worker",
    result: { event: "result", output: "done", workers: 1, run_id: RUN_ID },
    detail: {
      id: RUN_ID,
      plan: [{ id: "valuation", task: "Value AAPL", focus: "valuation" }],
      workers: [WORKER],
      max_workers: 4,
      output: "done",
      error: "",
    },
    select: (s) => s.workers as Record<string, unknown>[],
    pinned: ["tool_args", ARGS],
  },
  {
    name: "dag",
    hook: useDag as never,
    steps: [DAG_NODE],
    preamble: [
      {
        event: "plan",
        nodes: [
          {
            id: "a",
            task: "value AAPL",
            focus: "AAPL",
            tool: "company_snapshot",
            args: ARGS,
            depends_on: [],
            wave: 0,
          },
        ],
        waves: [["a"]],
      },
      { event: "wave", index: 0, node_ids: ["a"] },
    ],
    event: "node",
    result: { event: "result", output: "done", nodes: 1, waves: 1, run_id: RUN_ID },
    detail: {
      id: RUN_ID,
      plan: { nodes: [], waves: [["a"]] },
      nodes: [DAG_NODE],
      max_nodes: 6,
      output: "done",
      error: "",
    },
    select: (s) => s.nodes as Record<string, unknown>[],
    pinned: ["tool_args", ARGS],
  },
  {
    name: "autonomous",
    hook: useAutonomous as never,
    steps: [CYCLE],
    preamble: [
      { event: "goal", goal: "assess AAPL", backlog: ["look up AAPL"], max_cycles: 8 },
    ],
    event: "cycle",
    result: {
      event: "result",
      output: "done",
      cycles: 1,
      stop_reason: "complete",
      run_id: RUN_ID,
    },
    detail: {
      id: RUN_ID,
      goal: "assess AAPL",
      backlog: ["compare to sector"],
      cycles: [CYCLE],
      max_cycles: 8,
      stop_reason: "complete",
      output: "done",
      error: "",
    },
    select: (s) => s.cycles as Record<string, unknown>[],
    pinned: ["tool_args", ARGS],
  },
  {
    name: "browser",
    hook: useBrowserAgent as never,
    steps: [BROWSER_STEP],
    preamble: [
      { event: "started", max_steps: 15, provider: "ollama", allowed_domains: [], timeout_s: 300 },
    ],
    event: "step",
    result: {
      event: "result",
      output: "done",
      sources: [],
      stop_reason: "complete",
      steps: 1,
      run_id: RUN_ID,
    },
    detail: {
      id: RUN_ID,
      query: "nvda price",
      status: "done",
      steps: [BROWSER_STEP],
      max_steps: 15,
      urls_visited: [],
      stop_reason: "complete",
      output: "done",
      error: "",
    },
    select: (s) => s.steps as Record<string, unknown>[],
    pinned: ["action_args", { url: "https://example.test" }],
  },
  {
    name: "multiagent",
    hook: useMultiAgent as never,
    steps: [MULTI_STEP],
    preamble: [{ event: "route", agents: ["researcher"], reason: "needs data" }],
    event: "step",
    result: { event: "result", output: "done", agents: 1, run_id: RUN_ID },
    detail: {
      id: RUN_ID,
      agents: ["researcher"],
      route_reason: "needs data",
      steps: [MULTI_STEP],
      max_tools: 4,
      output: "done",
      error: "",
    },
    select: (s) => s.steps as Record<string, unknown>[],
  },
  {
    name: "eval_opt",
    hook: useEvaluate as never,
    steps: [ITERATION],
    preamble: [
      { event: "started", max_iterations: 3, threshold: 8 },
      { event: "draft", draft: "AAPL looks fairly valued." },
    ],
    event: "iteration",
    result: {
      event: "result",
      output: "done",
      iterations: 1,
      best_score: 7,
      run_id: RUN_ID,
    },
    detail: {
      id: RUN_ID,
      iterations: [ITERATION],
      max_iterations: 3,
      threshold: 8,
      best_score: 7,
      output: "done",
      error: "",
    },
    select: (s) => s.iterations as Record<string, unknown>[],
  },
  {
    name: "parallel",
    hook: useParallel as never,
    steps: [TASK],
    preamble: [
      { event: "started", strategy: "sectioning", tasks: [{ task_id: "valuation", label: "Valuation" }] },
    ],
    event: "task",
    result: {
      event: "result",
      strategy: "sectioning",
      output: "done",
      tally: null,
      run_id: RUN_ID,
    },
    detail: {
      id: RUN_ID,
      strategy: "sectioning",
      tasks: [TASK],
      tally: null,
      output: "done",
      error: "",
    },
    select: (s) => s.tasks as Record<string, unknown>[],
  },
];

describe("live stream state === refresh-restore state", () => {
  it.each(CASES)("$name", async ({ hook, steps, preamble, event, result, detail, select, pinned }) => {
    mockFetchSSE([
      ...preamble,
      // `event: ""` marks a workflow whose payload has no discriminator (chain).
      ...steps.map((step) => (event ? { event, ...step } : { run_id: RUN_ID, ...step })),
      result,
    ]);

    const streamed = renderHookWithQuery(hook);
    act(() => (streamed.result.current as { run: (q: string) => void }).run("is AAPL cheap"));
    await waitFor(() =>
      expect((streamed.result.current as { isRunning: boolean }).isRunning).toBe(false),
    );

    const restored = renderHookWithQuery(hook);
    act(() =>
      (
        restored.result.current as { loadFromDetail: (d: unknown) => void }
      ).loadFromDetail(detail),
    );

    const fromStream = select(streamed.result.current as never);
    const fromDetail = select(restored.result.current as never);

    // Length first: issue #7 was a step that was persisted but never streamed, so the
    // live list was SHORTER than the restored one while every card in it matched.
    expect(fromStream).toHaveLength(steps.length);
    expect(fromStream).toEqual(fromDetail);

    if (pinned) {
      // Named explicitly so a regression reports the field rather than a whole-object diff.
      const [field, value] = pinned;
      const i = steps.findIndex((s) => s[field] != null);
      expect(fromStream[i][field]).toEqual(value);
      expect(fromDetail[i][field]).toEqual(value);
    }
  });
});
