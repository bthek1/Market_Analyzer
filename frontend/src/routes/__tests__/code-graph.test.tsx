import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithQuery } from "@/test/render";
import type { CodeGraphPayload, CodeNodeDetail } from "@/types/codegraph";

const BASE = "http://localhost:8004";

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...actual,
    createFileRoute: () => (config: { component: React.ComponentType }) => config,
    Link: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
      <a {...props}>{children}</a>
    ),
    Outlet: () => null,
  };
});

vi.mock("@/components/layout/AppShell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

// ECharts renders to canvas (unsupported in jsdom); stand in a DOM shim with one button per
// node so selection stays testable.
interface MockNode {
  id: string;
  name: string;
}
vi.mock("echarts-for-react", () => ({
  default: ({
    option,
    onEvents,
  }: {
    option: { series: { data: MockNode[] }[] };
    onEvents?: { click?: (p: { dataType: string; data: MockNode }) => void };
  }) => (
    <div data-testid="echart">
      {option.series[0].data.map((n) => (
        <button
          key={n.id}
          type="button"
          onClick={() => onEvents?.click?.({ dataType: "node", data: n })}
        >
          {n.name}
        </button>
      ))}
    </div>
  ),
}));

const GRAPH: CodeGraphPayload = {
  nodes: [
    {
      id: "tools_run_tool",
      label: "run_tool()",
      file: "backend/apps/llm_analysis/tools.py",
      line: "L363",
      kind: "code",
      layer: "backend",
      module: "backend/apps/llm_analysis",
      community: 8,
      community_name: "Community 8",
      degree: 3,
    },
    {
      id: "react_run_react",
      label: "run_react()",
      file: "backend/apps/llm_analysis/react.py",
      line: "L182",
      kind: "code",
      layer: "backend",
      module: "backend/apps/llm_analysis",
      community: 5,
      community_name: "Community 5",
      degree: 1,
    },
    {
      id: "base_ui_react",
      label: "@base-ui/react",
      file: "frontend/package.json",
      line: "L15",
      kind: "concept",
      layer: "frontend",
      module: "frontend/package.json",
      community: 298,
      community_name: "Community 298",
      degree: 0,
    },
  ],
  edges: [
    {
      source: "react_run_react",
      target: "tools_run_tool",
      relation: "calls",
      confidence: "EXTRACTED",
      context: "call",
      file: "backend/apps/llm_analysis/react.py",
      line: "L182",
      weight: 1,
    },
  ],
  stats: {
    total_nodes: 4592,
    total_edges: 11099,
    matched_nodes: 3,
    returned_nodes: 3,
    returned_edges: 1,
    truncated: false,
    limit: 400,
  },
  facets: {
    kinds: [["code", 2]],
    layers: [
      ["backend", 2],
      ["frontend", 1],
    ],
    modules: [["backend/apps/llm_analysis", 2]],
    relations: [["calls", 1]],
    confidences: [["EXTRACTED", 1]],
  },
  built_at_commit: "abc1234def",
  generated_at: 1750000000,
};

const DETAIL: CodeNodeDetail = {
  id: "tools_run_tool",
  label: "run_tool()",
  file: "backend/apps/llm_analysis/tools.py",
  line: "L363",
  kind: "code",
  layer: "backend",
  module: "backend/apps/llm_analysis",
  community: 8,
  community_name: "Community 8",
  degree: 1,
  incoming: [
    {
      source: "react_run_react",
      target: "tools_run_tool",
      relation: "calls",
      confidence: "EXTRACTED",
      context: "call",
      file: "backend/apps/llm_analysis/react.py",
      line: "L182",
      weight: 1,
      node: {
        id: "react_run_react",
        label: "run_react()",
        file: "backend/apps/llm_analysis/react.py",
        line: "L182",
        kind: "code",
        layer: "backend",
        module: "backend/apps/llm_analysis",
        community: 5,
        community_name: "Community 5",
      },
    },
  ],
  outgoing: [],
};

let lastUrl: URL | null = null;

function mockGraph(payload: CodeGraphPayload = GRAPH) {
  server.use(
    http.get(`${BASE}/api/codegraph/graph/`, ({ request }) => {
      lastUrl = new URL(request.url);
      return HttpResponse.json(payload);
    }),
    http.get(`${BASE}/api/codegraph/nodes/:id/`, () => HttpResponse.json(DETAIL))
  );
}

async function renderPage() {
  const mod = await import("@/routes/code-graph");
  const Component = (mod.Route as unknown as { component: React.ComponentType }).component;
  return renderWithQuery(<Component />);
}

describe("code-graph route", () => {
  beforeEach(() => {
    lastUrl = null;
  });

  it("renders the graph nodes", async () => {
    mockGraph();
    await renderPage();
    expect(await screen.findByText("run_tool()")).toBeInTheDocument();
    expect(screen.getByText("run_react()")).toBeInTheDocument();
  });

  it("shows the stats line and the build commit", async () => {
    mockGraph();
    await renderPage();
    expect(await screen.findByText(/3 of 3 matching nodes/)).toBeInTheDocument();
    expect(screen.getByText(/Built at abc1234/)).toBeInTheDocument();
  });

  it("requests EXTRACTED edges only by default", async () => {
    mockGraph();
    await renderPage();
    await waitFor(() => expect(lastUrl).not.toBeNull());
    expect(lastUrl?.searchParams.get("confidence")).toBe("EXTRACTED");
  });

  it("drops the confidence filter when inferred edges are enabled", async () => {
    mockGraph();
    await renderPage();
    await screen.findByText("run_tool()");
    fireEvent.click(screen.getByLabelText(/Show inferred edges/i));
    await waitFor(() => expect(lastUrl?.searchParams.get("confidence")).toBeNull());
  });

  it("sends the layer filter", async () => {
    mockGraph();
    await renderPage();
    await screen.findByText("run_tool()");
    fireEvent.change(screen.getByLabelText("Layer"), { target: { value: "frontend" } });
    await waitFor(() => expect(lastUrl?.searchParams.get("layer")).toBe("frontend"));
  });

  it("sends the node limit", async () => {
    mockGraph();
    await renderPage();
    await screen.findByText("run_tool()");
    fireEvent.change(screen.getByLabelText("Node limit"), { target: { value: "800" } });
    await waitFor(() => expect(lastUrl?.searchParams.get("limit")).toBe("800"));
  });

  it("shows node detail with its callers when a node is selected", async () => {
    mockGraph();
    await renderPage();
    fireEvent.click(await screen.findByText("run_tool()"));
    expect(await screen.findByText(/Used by \(1\)/)).toBeInTheDocument();
    expect(
      screen.getByText("backend/apps/llm_analysis/tools.py:L363")
    ).toBeInTheDocument();
  });

  it("renders the not-built empty state on a 404 with a hint", async () => {
    server.use(
      http.get(`${BASE}/api/codegraph/graph/`, () =>
        HttpResponse.json(
          { detail: "The code graph has not been built yet.", hint: "Run `graphify extract .`" },
          { status: 404 }
        )
      )
    );
    await renderPage();
    expect(await screen.findByText("No code graph yet")).toBeInTheDocument();
    expect(screen.getByText(/graphify extract \./)).toBeInTheDocument();
  });

  it("shows an empty message when no nodes match", async () => {
    mockGraph({ ...GRAPH, nodes: [], edges: [], stats: { ...GRAPH.stats, matched_nodes: 0, returned_nodes: 0 } });
    await renderPage();
    expect(await screen.findByText("No nodes match these filters.")).toBeInTheDocument();
  });
});
