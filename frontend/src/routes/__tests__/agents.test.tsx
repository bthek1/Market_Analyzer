import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { screen, waitFor, within, fireEvent, act } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithQuery } from "@/test/render";
import {
  MOCK_CHAIN_RUN_DETAIL,
  MOCK_CHAIN_RUN_ID,
  MOCK_CHAIN_RUN_SUMMARY,
  MOCK_REACT_RUN_DETAIL,
  MOCK_REACT_RUN_SUMMARY,
} from "@/test/handlers";

const BASE = "http://localhost:8004";

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...actual,
    createFileRoute: () => (config: { component: React.ComponentType }) =>
      config,
    // `href={to}`, matching the copy in Sidebar.test.tsx. Without it the mock drops the
    // destination and every link on the page is untestable - and invisible to
    // getByRole("link"), which needs an href.
    Link: ({
      to,
      children,
      ...props
    }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { to: string }) => (
      <a href={to} {...props}>
        {children}
      </a>
    ),
    Outlet: () => null,
  };
});

vi.mock("@/components/layout/AppShell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

vi.mock("react-markdown", () => ({
  default: ({ children }: { children: string }) => (
    <div data-testid="markdown">{children}</div>
  ),
}));

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

// ---------------------------------------------------------------------------
// SSE helpers
// ---------------------------------------------------------------------------

function makeSSEStream(events: object[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const evt of events) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(evt)}\n\n`));
      }
      controller.close();
    },
  });
}

function fullRunEvents(runId = MOCK_CHAIN_RUN_ID): object[] {
  return [
    {
      run_id: runId,
      step_id: "__init__",
      label: "",
      status: "running",
      output: null,
      error: null,
    },
    {
      run_id: runId,
      step_id: "classify",
      label: "Classify Query",
      status: "running",
      output: null,
      error: null,
    },
    {
      run_id: runId,
      step_id: "classify",
      label: "Classify Query",
      status: "done",
      output: '{"intent":"analyse","tickers":["AAPL"]}',
      error: null,
    },
    {
      run_id: runId,
      step_id: "research",
      label: "Gather Data",
      status: "running",
      output: null,
      error: null,
    },
    {
      run_id: runId,
      step_id: "research",
      label: "Gather Data",
      status: "done",
      output: "[]",
      error: null,
    },
    {
      run_id: runId,
      step_id: "synthesise",
      label: "Synthesise",
      status: "running",
      output: null,
      error: null,
    },
    {
      run_id: runId,
      step_id: "synthesise",
      label: "Synthesise",
      status: "done",
      output: "Analysis text.",
      error: null,
    },
    {
      run_id: runId,
      step_id: "format",
      label: "Format Report",
      status: "running",
      output: null,
      error: null,
    },
    {
      run_id: runId,
      step_id: "format",
      label: "Format Report",
      status: "done",
      output: "## Summary\nStrong outlook.",
      error: null,
    },
    {
      run_id: runId,
      step_id: "__done__",
      label: "",
      status: "done",
      output: null,
      error: null,
    },
  ];
}

function mockFetchSSE(events: object[]) {
  // mockImplementation (not mockResolvedValue) so each fetch gets a fresh,
  // unread stream — running multiple workflows fires concurrent fetches.
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve({ ok: true, status: 200, body: makeSSEStream(events) }),
      ),
  );
}

// ---------------------------------------------------------------------------
// Workflow-panel helpers
//
// Each workflow panel owns a <select> whose current value is one of the agent
// types. The model selector is also a combobox, but its value is a model name,
// so we discriminate by the set of agent-type values.
// ---------------------------------------------------------------------------

const AGENT_VALUES = new Set([
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
]);

function workflowSelects(): HTMLSelectElement[] {
  return (screen.getAllByRole("combobox") as HTMLSelectElement[]).filter((s) =>
    AGENT_VALUES.has(s.value),
  );
}

function setWorkflow(type: string, index = 0) {
  fireEvent.change(workflowSelects()[index], { target: { value: type } });
}

function addWorkflow() {
  fireEvent.click(screen.getByRole("button", { name: /Add workflow/ }));
}

async function loadPage() {
  const { Route } = await import("@/routes/agents");
  const Page = Route.component as React.ComponentType;
  renderWithQuery(<Page />);
  await waitFor(() => screen.getByRole("button", { name: "Run" }));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Agents route", () => {
  it("exports a Route with a component", async () => {
    const mod = await import("@/routes/agents");
    expect(mod.Route).toBeDefined();
    expect(typeof mod.Route.component).toBe("function");
  });

  it("renders the Agents heading", async () => {
    await loadPage();
    await waitFor(() => expect(screen.getByText("Agents")).toBeTruthy());
  });

  it("renders a default Prompt Chain workflow panel", async () => {
    await loadPage();
    await waitFor(() => {
      const selects = workflowSelects();
      expect(selects.length).toBe(1);
      expect(selects[0].value).toBe("chain");
    });
  });

  it("Add workflow button appends a second panel", async () => {
    await loadPage();
    expect(workflowSelects().length).toBe(1);
    addWorkflow();
    await waitFor(() => expect(workflowSelects().length).toBe(2));
  });

  it("a second panel's selector excludes already-selected types", async () => {
    await loadPage();
    addWorkflow();
    await waitFor(() => expect(workflowSelects().length).toBe(2));
    const [first, second] = workflowSelects();
    // Default panel stays "chain"; the new panel takes the next unused type.
    expect(first.value).toBe("chain");
    expect(second.value).not.toBe("chain");
    // The new panel must not offer "chain" (already taken by the first panel).
    expect(Array.from(second.options).map((o) => o.value)).not.toContain(
      "chain",
    );
  });

  it("a panel can be removed once more than one exists", async () => {
    await loadPage();
    addWorkflow();
    await waitFor(() => expect(workflowSelects().length).toBe(2));
    const newType = workflowSelects()[1].value;
    const label = newType === "single" ? "Single Prompt" : newType; // first unused is "single"
    fireEvent.click(
      screen.getByRole("button", { name: new RegExp(`Remove ${label}`) }),
    );
    await waitFor(() => expect(workflowSelects().length).toBe(1));
  });

  it("shows the idle empty-state hint before running", async () => {
    await loadPage();
    await waitFor(() =>
      expect(screen.getByText("Press Run to start.")).toBeTruthy(),
    );
  });

  it("renders a workflow chip with a quick-remove per selected panel", async () => {
    await loadPage();
    // Default chain panel has a chip; a chip-level remove appears only once >1 panel.
    addWorkflow();
    await waitFor(() => expect(workflowSelects().length).toBe(2));
    expect(
      screen.getByRole("button", { name: "Remove Prompt Chain" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Remove Single Prompt" }),
    ).toBeTruthy();
  });

  it("shows an aggregate status line after a run completes", async () => {
    mockFetchSSE(fullRunEvents());
    await loadPage();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Analyse AAPL" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(screen.getByText("1 done")).toBeTruthy());
  });

  it("switching a panel to Autonomous shows the autonomous panel header", async () => {
    await loadPage();
    setWorkflow("autonomous");
    await waitFor(() => expect(screen.getByText(/Cycle budget:/)).toBeTruthy());
  });

  it("renders all four step labels on mount (default chain panel)", async () => {
    await loadPage();
    await waitFor(() => {
      expect(screen.getAllByText("Classify Query").length).toBeGreaterThan(0);
      expect(screen.getAllByText("Gather Data").length).toBeGreaterThan(0);
      expect(screen.getAllByText("Synthesise").length).toBeGreaterThan(0);
      expect(screen.getAllByText("Format Report").length).toBeGreaterThan(0);
    });
  });

  it("Run button is disabled when query is empty", async () => {
    await loadPage();
    const btn = screen.getByRole("button", {
      name: "Run",
    }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("Run button enabled after typing a query", async () => {
    await loadPage();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Analyse AAPL" },
    });
    await waitFor(() => {
      const btn = screen.getByRole("button", {
        name: "Run",
      }) as HTMLButtonElement;
      expect(btn.disabled).toBe(false);
    });
  });

  it("step cards transition through running -> done on full SSE stream", async () => {
    mockFetchSSE(fullRunEvents());
    await loadPage();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Analyse AAPL" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => {
      expect(screen.getAllByText("Format Report").length).toBeGreaterThan(0);
    });
  });

  it("final report is hidden before format step completes", async () => {
    await loadPage();
    await waitFor(() => expect(screen.queryByText("Final Report")).toBeNull());
  });

  it("final report renders after full SSE stream completes", async () => {
    mockFetchSSE(fullRunEvents());
    await loadPage();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Analyse AAPL" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(screen.getByText("Final Report")).toBeTruthy(), {
      timeout: 3000,
    });
    expect(screen.getByTestId("markdown")).toBeTruthy();
  });

  it("run_id is shown after __init__ event", async () => {
    mockFetchSSE(fullRunEvents());
    await loadPage();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() =>
      expect(screen.getByText(new RegExp(MOCK_CHAIN_RUN_ID))).toBeTruthy(),
    );
  });

  it("error step shows error message", async () => {
    const runId = MOCK_CHAIN_RUN_ID;
    mockFetchSSE([
      {
        run_id: runId,
        step_id: "__init__",
        label: "",
        status: "running",
        output: null,
        error: null,
      },
      {
        run_id: runId,
        step_id: "classify",
        label: "Classify Query",
        status: "running",
        output: null,
        error: null,
      },
      {
        run_id: runId,
        step_id: "classify",
        label: "Classify Query",
        status: "error",
        output: null,
        error: "LLM unavailable",
      },
      {
        run_id: runId,
        step_id: "__done__",
        label: "",
        status: "error",
        output: null,
        error: null,
      },
    ]);
    await loadPage();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() =>
      expect(screen.getAllByText("LLM unavailable").length).toBeGreaterThan(0),
    );
  });

  it("switching a panel's type in place resets the previous workflow's output", async () => {
    mockFetchSSE(fullRunEvents());
    await loadPage();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Analyse AAPL" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(screen.getByText("Final Report")).toBeTruthy());

    // Switch the single panel chain -> react: the chain result must be cleared.
    setWorkflow("react");
    await waitFor(() => expect(screen.queryByText("Final Report")).toBeNull());
    // The panel now reflects the ReAct workflow (its tool-budget header).
    expect(screen.getByText(/Tool calls:/)).toBeTruthy();
  });

  it("runs every selected workflow on submit (fans out to each panel)", async () => {
    mockFetchSSE(fullRunEvents());
    await loadPage();
    // Default chain panel + a single-prompt panel.
    addWorkflow();
    await waitFor(() => expect(workflowSelects().length).toBe(2));
    setWorkflow("single", 1);

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Compare MSFT" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    // Chain panel: streamed steps visible (via stubbed fetch SSE).
    await waitFor(() =>
      expect(screen.getAllByText("Classify Query").length).toBeGreaterThan(0),
    );
    // Single panel: markdown answer from the chat endpoint (via MSW/axios).
    await waitFor(() =>
      expect(screen.getAllByTestId("markdown").length).toBeGreaterThan(0),
    );
  });

  it("Settings button opens the settings drawer with the LLM Settings form", async () => {
    await loadPage();
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    await waitFor(() =>
      expect(screen.getByText("LLM Settings", { selector: "h2" })).toBeTruthy(),
    );
  });

  it("offers a two-way switch to the chat workspace", async () => {
    // Chat was a MODE here until issue #8 phase 6. It moved to /chat for the same reason
    // /browse is its own page - this one compares one-shot workflows over a single query,
    // and a conversation is not comparable to a one-shot run - but the two stay one click
    // apart, and the switch has to work in BOTH directions to be worth having.
    await loadPage();

    // Scoped to the switch - the AppShell sidebar carries its own "Chat" nav link.
    const switcher = within(screen.getByRole("navigation", { name: "Workspace" }));
    const chat = switcher.getByRole("link", { name: "Chat" });
    const workflows = switcher.getByRole("link", { name: "Workflows" });

    expect(chat).toHaveAttribute("href", "/chat");
    expect(workflows).toHaveAttribute("href", "/agents");
    expect(workflows).toHaveAttribute("aria-current", "page");
    // Still the workflow workspace, not a chat mode wearing its clothes.
    expect(workflowSelects().length).toBe(1);
  });

  it("restores the saved workspace and rehydrates the run after a reload", async () => {
    localStorage.setItem(
      "agents.session.v1",
      JSON.stringify({
        // A pre-issue-#8 payload still carries `mode`; it is simply no longer read.
        mode: "workflows",
        selectedTypes: ["chain"],
        query: "Analyse AAPL",
        runs: { chain: MOCK_CHAIN_RUN_ID },
      }),
    );
    await loadPage();
    // The persisted (done) chain run is reloaded from its detail endpoint.
    await waitFor(() => expect(screen.getByText("Final Report")).toBeTruthy());
  });

  it("keeps the workspace busy while a restored run is still running", async () => {
    server.use(
      http.get(`${BASE}/api/llm/chain/:id/`, () =>
        HttpResponse.json({ ...MOCK_CHAIN_RUN_DETAIL, status: "running" }),
      ),
    );
    localStorage.setItem(
      "agents.session.v1",
      JSON.stringify({
        mode: "workflows",
        selectedTypes: ["chain"],
        query: "Analyse AAPL",
        runs: { chain: MOCK_CHAIN_RUN_ID },
      }),
    );
    const { Route } = await import("@/routes/agents");
    const Page = Route.component as React.ComponentType;
    renderWithQuery(<Page />);
    // Once the persisted run is rehydrated, reconnecting to its "running" status
    // holds the Run button in its busy state.
    await waitFor(() => expect(screen.getByText("Final Report")).toBeTruthy());
    expect(screen.getByRole("button", { name: /Running/ })).toBeTruthy();
  });

  it("Stop cancels a running workflow via the stop endpoint", async () => {
    let stopped = false;
    server.use(
      http.post(`${BASE}/api/llm/runs/stop/`, () => {
        stopped = true;
        return HttpResponse.json({ stopped: true });
      }),
    );
    // A stream that starts the run but never sends __done__, so it stays running.
    mockFetchSSE([
      { run_id: MOCK_CHAIN_RUN_ID, step_id: "__init__", label: "", status: "running", output: null, error: null },
      { run_id: MOCK_CHAIN_RUN_ID, step_id: "classify", label: "Classify Query", status: "running", output: null, error: null },
    ]);
    await loadPage();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Analyse AAPL" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "Stop" }).length).toBeGreaterThan(0),
    );
    await act(async () => {
      fireEvent.click(screen.getAllByRole("button", { name: "Stop" })[0]);
    });
    await waitFor(() => expect(stopped).toBe(true));
  });

  it("Stop on a running history row cancels that run", async () => {
    let stopped = false;
    server.use(
      http.get(`${BASE}/api/llm/chain/`, () =>
        HttpResponse.json({
          count: 1,
          next: null,
          previous: null,
          results: [{ ...MOCK_CHAIN_RUN_SUMMARY, status: "running" }],
        }),
      ),
      http.post(`${BASE}/api/llm/runs/stop/`, () => {
        stopped = true;
        return HttpResponse.json({ stopped: true });
      }),
    );
    await loadPage();
    // The history sidebar is open by default; a running row exposes a Stop action.
    await waitFor(() => screen.getByText(MOCK_CHAIN_RUN_SUMMARY.query));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    });
    await waitFor(() => expect(stopped).toBe(true));
  });

  it("history button opens drawer showing run list", async () => {
    await loadPage();
    await waitFor(() =>
      expect(screen.getByText(MOCK_CHAIN_RUN_SUMMARY.query)).toBeTruthy(),
    );
  });

  it("history aggregates runs across workflow types and replays a non-chain run", async () => {
    server.use(
      http.get(`${BASE}/api/llm/react/history/`, () =>
        HttpResponse.json({
          count: 1,
          next: null,
          previous: null,
          results: [MOCK_REACT_RUN_SUMMARY],
        }),
      ),
      http.get(`${BASE}/api/llm/react/:id/`, () =>
        HttpResponse.json(MOCK_REACT_RUN_DETAIL),
      ),
    );
    await loadPage();

    // The unified drawer lists runs from multiple workflows (chain + react).
    await waitFor(() => screen.getByText(MOCK_REACT_RUN_SUMMARY.query));
    expect(screen.getByText(MOCK_CHAIN_RUN_SUMMARY.query)).toBeTruthy();

    // Selecting the react run swaps the workspace to a single ReAct panel and
    // replays its persisted steps.
    await act(async () => {
      fireEvent.click(screen.getByText(MOCK_REACT_RUN_SUMMARY.query));
    });
    await waitFor(() =>
      expect(screen.getByText("I need AAPL valuation")).toBeTruthy(),
    );
    expect(workflowSelects()[0].value).toBe("react");
  });

  it("clicking history row in drawer loads run detail steps", async () => {
    await loadPage();
    await waitFor(() => screen.getByText(MOCK_CHAIN_RUN_SUMMARY.query));
    await act(async () => {
      fireEvent.click(screen.getByText(MOCK_CHAIN_RUN_SUMMARY.query));
    });
    await waitFor(() => expect(screen.getByText("Final Report")).toBeTruthy());
  });

  it("Reset button resets step states", async () => {
    mockFetchSSE(fullRunEvents());
    await loadPage();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Analyse AAPL" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => screen.getByText("Final Report"));
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    await waitFor(() => expect(screen.queryByText("Final Report")).toBeNull());
  });

  it("Ctrl+Enter submits the form", async () => {
    mockFetchSSE(fullRunEvents());
    await loadPage();
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "Analyse AAPL" } });
    fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled());
  });

  it("history drawer shows correct status badge", async () => {
    await loadPage();
    await waitFor(() => expect(screen.getByText("done")).toBeTruthy());
  });

  it("history drawer shows error run with error badge", async () => {
    server.use(
      http.get(`${BASE}/api/llm/chain/`, () =>
        HttpResponse.json({
          count: 1,
          next: null,
          previous: null,
          results: [{ ...MOCK_CHAIN_RUN_SUMMARY, status: "error" }],
        }),
      ),
    );
    await loadPage();
    await waitFor(() => expect(screen.getByText("error")).toBeTruthy());
  });

  it("shows model selector populated from API", async () => {
    await loadPage();
    await waitFor(() => {
      const options = screen.getAllByRole("option");
      expect(options.some((o) => o.textContent === "llama3.2:latest")).toBe(
        true,
      );
    });
  });

  it("detail load populates steps from DB without triggering the chain/run/ streaming endpoint", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    await loadPage();
    await waitFor(() => screen.getByText(MOCK_CHAIN_RUN_SUMMARY.query));
    await act(async () => {
      fireEvent.click(screen.getByText(MOCK_CHAIN_RUN_SUMMARY.query));
    });
    await waitFor(() => screen.getByText("Final Report"));
    const streamingCalls = fetchSpy.mock.calls.filter((args: unknown[]) =>
      String(args[0]).includes("/chain/run/"),
    );
    expect(streamingCalls.length).toBe(0);
  });

  it("switching a panel to Single Prompt shows the single prompt panel", async () => {
    await loadPage();
    setWorkflow("single");
    await waitFor(() =>
      expect(
        screen.getByText("Single Prompt", { selector: "h2" }),
      ).toBeTruthy(),
    );
  });

  it("Single Prompt panel calls chat endpoint and shows response", async () => {
    await loadPage();
    setWorkflow("single");
    await waitFor(() => screen.getByText("Single Prompt", { selector: "h2" }));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "What is AAPL?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => screen.getByTestId("markdown"));
    expect(screen.getByTestId("markdown").textContent).toBe(
      "Hello from Ollama!",
    );
  });

  it("Single Prompt panel shows elapsed time after response", async () => {
    await loadPage();
    setWorkflow("single");
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => {
      const timeBadges = screen.queryAllByText(/^\d+\.\d+s$/);
      expect(timeBadges.length).toBeGreaterThan(0);
    });
  });

  it("StepCard shows Input toggle after classify completes, expands query on click", async () => {
    mockFetchSSE(fullRunEvents());
    await loadPage();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Analyse AAPL" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => screen.getByText("Final Report"), { timeout: 3000 });

    const inputSpans = screen.getAllByText("Input");
    expect(inputSpans.length).toBeGreaterThan(0);
    fireEvent.click(inputSpans[0]);
    await waitFor(() => {
      const pres = document.querySelectorAll("pre");
      const hasQuery = Array.from(pres).some((p) =>
        p.textContent?.includes("Analyse AAPL"),
      );
      expect(hasQuery).toBe(true);
    });
  });

  it("StepCard output expands from paragraph to pre on Output button click", async () => {
    mockFetchSSE(fullRunEvents());
    await loadPage();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => screen.getByText("Final Report"), { timeout: 3000 });

    const outputSpans = screen.getAllByText("Output");
    expect(outputSpans.length).toBeGreaterThan(0);
    fireEvent.click(outputSpans[0]);
    await waitFor(() => {
      const pres = document.querySelectorAll("pre");
      const hasClassifyOutput = Array.from(pres).some((p) =>
        p.textContent?.includes('"intent"'),
      );
      expect(hasClassifyOutput).toBe(true);
    });
  });

  it("history drawer close button hides drawer content", async () => {
    await loadPage();
    await waitFor(() => screen.getByText(MOCK_CHAIN_RUN_SUMMARY.query));
    fireEvent.click(screen.getByText("×"));
    await waitFor(() =>
      expect(screen.queryByText(MOCK_CHAIN_RUN_SUMMARY.query)).toBeNull(),
    );
  });

  it("history drawer empty state shows placeholder", async () => {
    server.use(
      http.get(`${BASE}/api/llm/chain/`, () =>
        HttpResponse.json({
          count: 0,
          next: null,
          previous: null,
          results: [],
        }),
      ),
    );
    await loadPage();
    await waitFor(() => expect(screen.getByText("No runs yet.")).toBeTruthy());
  });

  // -------------------------------------------------------------------------
  // Routing
  // -------------------------------------------------------------------------

  function routeSimpleEvents(): object[] {
    return [
      {
        event: "classified",
        route: "simple",
        reason: "Factual price lookup",
        tickers: ["AAPL"],
        complexity: "low",
      },
      {
        event: "result",
        route: "simple",
        output: "AAPL trades around $200.",
        run_id: MOCK_CHAIN_RUN_ID,
      },
    ];
  }

  function routeDeepEvents(): object[] {
    return [
      {
        event: "classified",
        route: "deep_research",
        reason: "Multi-ticker thesis",
        tickers: ["AAPL", "MSFT"],
        complexity: "high",
      },
      {
        run_id: MOCK_CHAIN_RUN_ID,
        step_id: "__init__",
        label: "",
        status: "running",
        output: null,
        error: null,
      },
      {
        run_id: MOCK_CHAIN_RUN_ID,
        step_id: "classify",
        label: "Classify Query",
        status: "done",
        output: "{}",
        error: null,
      },
      {
        run_id: MOCK_CHAIN_RUN_ID,
        step_id: "research",
        label: "Gather Data",
        status: "done",
        output: "[]",
        error: null,
      },
      {
        run_id: MOCK_CHAIN_RUN_ID,
        step_id: "synthesise",
        label: "Synthesise",
        status: "done",
        output: "Analysis.",
        error: null,
      },
      {
        run_id: MOCK_CHAIN_RUN_ID,
        step_id: "format",
        label: "Format Report",
        status: "done",
        output: "## Summary\nStrong.",
        error: null,
      },
      {
        run_id: MOCK_CHAIN_RUN_ID,
        step_id: "__done__",
        label: "",
        status: "done",
        output: null,
        error: null,
      },
      {
        event: "result",
        route: "deep_research",
        output: "## Summary\nStrong.",
        run_id: MOCK_CHAIN_RUN_ID,
      },
    ];
  }

  it("Routing panel simple route renders RouteDecisionCard with label and reason", async () => {
    mockFetchSSE(routeSimpleEvents());
    await loadPage();
    setWorkflow("route");
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "AAPL price?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => expect(screen.getByText("Route Decided")).toBeTruthy());
    expect(screen.getByText("SIMPLE")).toBeTruthy();
    expect(screen.getByText("Factual price lookup")).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByText("AAPL trades around $200.")).toBeTruthy(),
    );
  });

  it("Routing panel deep_research renders chain StepCards", async () => {
    mockFetchSSE(routeDeepEvents());
    await loadPage();
    setWorkflow("route");
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Thesis on AAPL vs MSFT" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => expect(screen.getByText("DEEP RESEARCH")).toBeTruthy());
    await waitFor(() =>
      expect(screen.getAllByText("Format Report").length).toBeGreaterThan(0),
    );
  });

  // -------------------------------------------------------------------------
  // Parallel
  // -------------------------------------------------------------------------

  function parallelSectioningEvents(): object[] {
    return [
      {
        event: "started",
        strategy: "sectioning",
        tasks: [
          { task_id: "valuation", label: "Valuation" },
          { task_id: "profitability", label: "Profitability" },
          { task_id: "risk", label: "Risk" },
        ],
      },
      {
        event: "task",
        task_id: "valuation",
        label: "Valuation",
        status: "done",
        output: "cheap",
        vote: null,
        error: null,
      },
      {
        event: "task",
        task_id: "profitability",
        label: "Profitability",
        status: "done",
        output: "strong",
        vote: null,
        error: null,
      },
      {
        event: "task",
        task_id: "risk",
        label: "Risk",
        status: "done",
        output: "low",
        vote: null,
        error: null,
      },
      {
        event: "result",
        strategy: "sectioning",
        output: "Final synthesis.",
        tally: null,
        run_id: MOCK_CHAIN_RUN_ID,
      },
    ];
  }

  function parallelVotingEvents(): object[] {
    return [
      {
        event: "started",
        strategy: "voting",
        tasks: [
          { task_id: "vote_0", label: "Vote 1" },
          { task_id: "vote_1", label: "Vote 2" },
          { task_id: "vote_2", label: "Vote 3" },
        ],
      },
      {
        event: "task",
        task_id: "vote_0",
        label: "Vote 1",
        status: "done",
        output: "r",
        vote: "buy",
        error: null,
      },
      {
        event: "task",
        task_id: "vote_1",
        label: "Vote 2",
        status: "done",
        output: "r",
        vote: "buy",
        error: null,
      },
      {
        event: "task",
        task_id: "vote_2",
        label: "Vote 3",
        status: "done",
        output: "r",
        vote: "hold",
        error: null,
      },
      {
        event: "result",
        strategy: "voting",
        output: "Consensus rationale.",
        tally: { buy: 2, hold: 1, sell: 0 },
        run_id: MOCK_CHAIN_RUN_ID,
      },
    ];
  }

  it("Parallel panel sectioning renders three aspect cards in a grid", async () => {
    mockFetchSSE(parallelSectioningEvents());
    await loadPage();
    setWorkflow("parallel");
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Analyse AAPL" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => {
      expect(screen.getByText("Valuation")).toBeTruthy();
      expect(screen.getByText("Profitability")).toBeTruthy();
      expect(screen.getByText("Risk")).toBeTruthy();
    });
    await waitFor(() => expect(screen.getByTestId("markdown")).toBeTruthy());
  });

  it("Parallel panel strategy toggle switches to voting and shows the votes stepper", async () => {
    await loadPage();
    setWorkflow("parallel");
    await waitFor(() => screen.getByRole("button", { name: "Voting" }));
    expect(screen.queryByRole("spinbutton")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Voting" }));
    await waitFor(() => expect(screen.getByRole("spinbutton")).toBeTruthy());
  });

  it("Parallel panel voting renders vote cards and VoteTally consensus", async () => {
    mockFetchSSE(parallelVotingEvents());
    await loadPage();
    setWorkflow("parallel");
    fireEvent.click(screen.getByRole("button", { name: "Voting" }));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Buy AAPL?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => expect(screen.getByText("Vote 1 (buy)")).toBeTruthy());
    expect(screen.getByText("Vote 3 (hold)")).toBeTruthy();
    await waitFor(() => expect(screen.getByText(/Consensus:/)).toBeTruthy());
    expect(screen.getByText("BUY")).toBeTruthy();
  });

  it("Parallel voting tie resolves consensus to HOLD", async () => {
    mockFetchSSE([
      {
        event: "started",
        strategy: "voting",
        tasks: [
          { task_id: "vote_0", label: "Vote 1" },
          { task_id: "vote_1", label: "Vote 2" },
        ],
      },
      {
        event: "task",
        task_id: "vote_0",
        label: "Vote 1",
        status: "done",
        output: "r",
        vote: "buy",
        error: null,
      },
      {
        event: "task",
        task_id: "vote_1",
        label: "Vote 2",
        status: "done",
        output: "r",
        vote: "sell",
        error: null,
      },
      {
        event: "result",
        strategy: "voting",
        output: "split panel",
        tally: { buy: 1, hold: 0, sell: 1 },
        run_id: MOCK_CHAIN_RUN_ID,
      },
    ]);
    await loadPage();
    setWorkflow("parallel");
    fireEvent.click(screen.getByRole("button", { name: "Voting" }));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Buy AAPL?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => expect(screen.getByText(/Consensus:/)).toBeTruthy());
    expect(screen.getByText("HOLD")).toBeTruthy();
  });

  it("Parallel panel renders an error message on an error event", async () => {
    mockFetchSSE([{ event: "error", error: "All vote calls failed." }]);
    await loadPage();
    setWorkflow("parallel");
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Buy AAPL?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() =>
      expect(screen.getByText("All vote calls failed.")).toBeTruthy(),
    );
  });

  // -------------------------------------------------------------------------
  // ReAct
  // -------------------------------------------------------------------------

  function reactEvents(): object[] {
    return [
      {
        event: "started",
        max_steps: 6,
        tools: ["company_snapshot", "recent_price"],
      },
      {
        event: "step",
        id: "row-0",
        order: 0,
        thought: "I need AAPL valuation",
        tool: "company_snapshot",
        tool_args: { symbol: "AAPL" },
        observation: '{"trailing_pe": 31.2}',
        is_answer: false,
        status: "done",
        error: null,
      },
      {
        event: "step",
        id: "row-1",
        order: 1,
        thought: "I have enough to answer",
        tool: "",
        tool_args: null,
        observation: "",
        is_answer: true,
        status: "done",
        error: null,
      },
      {
        event: "result",
        output: "## Verdict\nAAPL is fairly valued.",
        run_id: MOCK_CHAIN_RUN_ID,
      },
    ];
  }

  it("ReAct panel renders Thought/Action/Observation steps and the final answer", async () => {
    mockFetchSSE(reactEvents());
    await loadPage();
    setWorkflow("react");
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Is AAPL cheap?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => {
      expect(screen.getByText("I need AAPL valuation")).toBeTruthy();
      expect(screen.getByText(/company_snapshot/)).toBeTruthy();
      expect(screen.getByText("Final reasoning")).toBeTruthy();
    });
    await waitFor(() => expect(screen.getByTestId("markdown")).toBeTruthy());
  });

  it("ReAct panel renders an error message on an error event", async () => {
    mockFetchSSE([
      { event: "started", max_steps: 6, tools: [] },
      { event: "error", error: "Ollama service unavailable." },
    ]);
    await loadPage();
    setWorkflow("react");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() =>
      expect(screen.getByText("Ollama service unavailable.")).toBeTruthy(),
    );
  });

  // -------------------------------------------------------------------------
  // Evaluator-Optimizer
  // -------------------------------------------------------------------------

  function evaluateEvents(): object[] {
    return [
      { event: "started", max_iterations: 3, threshold: 8 },
      { event: "draft", draft: "Initial draft answer." },
      {
        event: "iteration",
        order: 0,
        draft: "Initial draft answer.",
        score: 5,
        feedback: "Add free cash flow discussion.",
        passed: false,
        status: "done",
      },
      {
        event: "iteration",
        order: 1,
        draft: "Revised answer with FCF.",
        score: 9,
        feedback: "Well grounded and complete.",
        passed: true,
        status: "done",
      },
      {
        event: "result",
        output: "## Verdict\nRevised answer with FCF.",
        iterations: 2,
        best_score: 9,
        run_id: MOCK_CHAIN_RUN_ID,
      },
    ];
  }

  it("Evaluate panel renders Draft/Score/Feedback iterations and the final answer", async () => {
    mockFetchSSE(evaluateEvents());
    await loadPage();
    setWorkflow("evaluate");
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Is AAPL cheap?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => {
      expect(screen.getByText("Score 5/10")).toBeTruthy();
      expect(screen.getByText("Add free cash flow discussion.")).toBeTruthy();
      expect(screen.getByText("Score 9/10")).toBeTruthy();
      expect(screen.getByText(/Final Answer \(best, 9\/10\)/)).toBeTruthy();
    });
    await waitFor(() =>
      expect(screen.getAllByTestId("markdown").length).toBeGreaterThan(0),
    );
  });

  it("Evaluate panel renders an error message on an error event", async () => {
    mockFetchSSE([
      { event: "started", max_iterations: 3, threshold: 8 },
      { event: "error", error: "Ollama service unavailable." },
    ]);
    await loadPage();
    setWorkflow("evaluate");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() =>
      expect(screen.getByText("Ollama service unavailable.")).toBeTruthy(),
    );
  });

  // -------------------------------------------------------------------------
  // Plan-and-Execute
  // -------------------------------------------------------------------------

  function planEvents(): object[] {
    return [
      { event: "started", max_steps: 6, allow_replan: true },
      {
        event: "plan",
        steps: [
          {
            task: "Fetch AAPL valuation",
            tool: "company_snapshot",
            args: { symbol: "AAPL" },
          },
          { task: "Write the verdict", tool: null, args: null },
        ],
      },
      {
        event: "step",
        id: "row-0",
        order: 0,
        task: "Fetch AAPL valuation",
        tool: "company_snapshot",
        tool_args: { symbol: "AAPL" },
        observation: '{"trailing_pe": 31.2}',
        result: "AAPL trades at 31x earnings.",
        status: "done",
      },
      {
        event: "step",
        order: 1,
        task: "Write the verdict",
        id: "row-1",
        tool: "",
        tool_args: null,
        observation: null,
        result: "Fairly valued.",
        status: "done",
      },
      {
        event: "result",
        output: "## Verdict\nFairly valued.",
        steps: 2,
        replans: 0,
        run_id: MOCK_CHAIN_RUN_ID,
      },
    ];
  }

  it("Plan panel renders the upfront plan, executed steps, and the final answer", async () => {
    mockFetchSSE(planEvents());
    await loadPage();
    setWorkflow("plan");
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Is AAPL cheap?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => {
      expect(screen.getByText("Execution")).toBeTruthy();
      expect(
        screen.getAllByText("Fetch AAPL valuation").length,
      ).toBeGreaterThan(1);
      expect(screen.getByText("AAPL trades at 31x earnings.")).toBeTruthy();
    });
    await waitFor(() =>
      expect(screen.getAllByTestId("markdown").length).toBeGreaterThan(0),
    );
  });

  it("Plan panel renders an error message on an error event", async () => {
    mockFetchSSE([
      { event: "started", max_steps: 6, allow_replan: true },
      { event: "error", error: "Planner did not return a usable plan." },
    ]);
    await loadPage();
    setWorkflow("plan");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() =>
      expect(
        screen.getByText("Planner did not return a usable plan."),
      ).toBeTruthy(),
    );
  });

  // -------------------------------------------------------------------------
  // Orchestrator-Workers
  // -------------------------------------------------------------------------

  function orchestrateEvents(): object[] {
    return [
      { event: "started", max_workers: 4 },
      {
        event: "plan",
        subtasks: [
          {
            task: "Summarise AAPL valuation vs sector",
            focus: "valuation",
            tool: "sector_analysis",
            args: { sector: "Technology" },
          },
          {
            task: "Assess balance-sheet risk",
            focus: "risk",
            tool: null,
            args: null,
          },
        ],
      },
      {
        event: "worker",
        worker_id: "valuation",
        label: "valuation",
        order: 0,
        task: "Summarise AAPL valuation vs sector",
        tool: "sector_analysis",
        tool_args: { sector: "Technology" },
        observation: '{"metrics": {}}',
        output: "AAPL trades above its sector median.",
        status: "done",
        error: null,
      },
      {
        event: "worker",
        worker_id: "risk",
        label: "risk",
        order: 1,
        task: "Assess balance-sheet risk",
        tool: "",
        tool_args: null,
        observation: "",
        output: "Balance sheet is solid.",
        status: "done",
        error: null,
      },
      {
        event: "result",
        output: "## Verdict\nFairly valued.",
        workers: 2,
        run_id: MOCK_CHAIN_RUN_ID,
      },
    ];
  }

  it("Orchestrate panel renders the decomposition, worker cards, and final answer", async () => {
    mockFetchSSE(orchestrateEvents());
    await loadPage();
    setWorkflow("orchestrate");
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Give me a full picture of AAPL" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => {
      expect(screen.getByText("Decomposition")).toBeTruthy();
      expect(screen.getByText("Workers (concurrent)")).toBeTruthy();
      expect(
        screen.getAllByText("Summarise AAPL valuation vs sector").length,
      ).toBeGreaterThan(1);
      expect(
        screen.getByText("AAPL trades above its sector median."),
      ).toBeTruthy();
    });
    await waitFor(() =>
      expect(screen.getAllByTestId("markdown").length).toBeGreaterThan(0),
    );
  });

  it("Orchestrate panel renders an error message on an error event", async () => {
    mockFetchSSE([
      { event: "started", max_workers: 4 },
      {
        event: "error",
        error: "Orchestrator did not return a usable decomposition.",
      },
    ]);
    await loadPage();
    setWorkflow("orchestrate");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() =>
      expect(
        screen.getByText("Orchestrator did not return a usable decomposition."),
      ).toBeTruthy(),
    );
  });

  // -------------------------------------------------------------------------
  // Multi-Agent (Sequential)
  // -------------------------------------------------------------------------

  function multiAgentEvents(): object[] {
    return [
      {
        event: "route",
        agents: ["researcher", "analyst", "writer"],
        reason: "Needs data, interpretation, and a report.",
      },
      {
        event: "step",
        agent_id: "researcher",
        label: "Researcher",
        order: 0,
        input: "Is AAPL cheap?",
        tool_calls: [
          {
            tool: "company_snapshot",
            args: { symbol: "AAPL" },
            observation: '{"trailing_pe": 30}',
          },
        ],
        output: "AAPL trades at a P/E of 30.",
        status: "done",
        error: null,
      },
      {
        event: "step",
        agent_id: "analyst",
        label: "Analyst",
        order: 1,
        input: "AAPL trades at a P/E of 30.",
        tool_calls: null,
        output: "That is rich versus history.",
        status: "done",
        error: null,
      },
      {
        event: "step",
        agent_id: "writer",
        label: "Writer",
        order: 2,
        input: "That is rich versus history.",
        tool_calls: null,
        output: "AAPL looks fully valued.",
        status: "done",
        error: null,
      },
      {
        event: "result",
        output: "## Verdict\nFully valued.",
        agents: 3,
        run_id: MOCK_CHAIN_RUN_ID,
      },
    ];
  }

  it("Multi-Agent panel renders the roster, stage cards, and final answer", async () => {
    mockFetchSSE(multiAgentEvents());
    await loadPage();
    setWorkflow("multiagent");
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Is AAPL cheap?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => {
      expect(screen.getByText("Roster")).toBeTruthy();
      expect(screen.getByText("Pipeline (sequential)")).toBeTruthy();
      expect(screen.getByText("Researcher")).toBeTruthy();
      expect(screen.getByText("Tool calls (1)")).toBeTruthy();
    });
    await waitFor(() =>
      expect(screen.getAllByTestId("markdown").length).toBeGreaterThan(0),
    );
  });

  it("Multi-Agent panel renders an error message on an error event", async () => {
    mockFetchSSE([{ event: "error", error: "All sub-agents failed." }]);
    await loadPage();
    setWorkflow("multiagent");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() =>
      expect(screen.getByText("All sub-agents failed.")).toBeTruthy(),
    );
  });

  // -------------------------------------------------------------------------
  // Multi-Agent (Parallel / DAG)
  // -------------------------------------------------------------------------

  function dagEvents(): object[] {
    return [
      {
        event: "plan",
        nodes: [
          {
            id: "a",
            task: "value AAPL",
            focus: "AAPL",
            tool: "company_snapshot",
            args: { symbol: "AAPL" },
            depends_on: [],
            wave: 0,
          },
          {
            id: "b",
            task: "value MSFT",
            focus: "MSFT",
            tool: "company_snapshot",
            args: { symbol: "MSFT" },
            depends_on: [],
            wave: 0,
          },
          {
            id: "c",
            task: "compare",
            focus: "Verdict",
            tool: null,
            args: null,
            depends_on: ["a", "b"],
            wave: 1,
          },
        ],
        waves: [["a", "b"], ["c"]],
      },
      { event: "wave", index: 0, node_ids: ["a", "b"] },
      {
        event: "node",
        id: "row-a",
        node_id: "a",
        label: "AAPL",
        wave: 0,
        order: 0,
        task: "value AAPL",
        tool: "company_snapshot",
        tool_args: { symbol: "AAPL" },
        observation: '{"trailing_pe": 30}',
        depends_on: [],
        output: "AAPL P/E 30.",
        status: "done",
        error: null,
      },
      {
        event: "node",
        id: "row-b",
        node_id: "b",
        label: "MSFT",
        wave: 0,
        order: 1,
        task: "value MSFT",
        tool: "company_snapshot",
        tool_args: { symbol: "MSFT" },
        observation: '{"trailing_pe": 20}',
        depends_on: [],
        output: "MSFT P/E 20.",
        status: "done",
        error: null,
      },
      { event: "wave", index: 1, node_ids: ["c"] },
      {
        event: "node",
        id: "row-c",
        node_id: "c",
        label: "Verdict",
        wave: 1,
        order: 2,
        task: "compare",
        tool: null,
        tool_args: null,
        observation: null,
        depends_on: ["a", "b"],
        output: "MSFT is cheaper.",
        status: "done",
        error: null,
      },
      {
        event: "result",
        output: "## Verdict\nMSFT is cheaper.",
        nodes: 3,
        waves: 2,
        run_id: MOCK_CHAIN_RUN_ID,
      },
    ];
  }

  it("DAG panel renders the wave rows, node cards with depends_on, and final answer", async () => {
    mockFetchSSE(dagEvents());
    await loadPage();
    setWorkflow("dag");
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Compare AAPL and MSFT" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => {
      expect(screen.getByText("3 nodes, 2 waves")).toBeTruthy();
      expect(screen.getByText("Wave 0")).toBeTruthy();
      expect(screen.getByText("Wave 1")).toBeTruthy();
      expect(screen.getByText("<- a, b")).toBeTruthy();
    });
    await waitFor(() =>
      expect(screen.getAllByTestId("markdown").length).toBeGreaterThan(0),
    );
  });

  it("DAG panel renders an error message on an error event", async () => {
    mockFetchSSE([{ event: "error", error: "All nodes failed." }]);
    await loadPage();
    setWorkflow("dag");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() =>
      expect(screen.getByText("All nodes failed.")).toBeTruthy(),
    );
  });
});
