import React from "react";
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithQuery } from "@/test/render";
import type { Concept, ConceptDetail, GraphPayload } from "@/types/knowledge";

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

// ECharts renders to canvas (unsupported in jsdom); mock it to a DOM stand-in with one
// button per node so node selection/expansion stays testable.
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
          data-testid={`concept-node-${n.id}`}
          onClick={() => onEvents?.click?.({ dataType: "node", data: n })}
        >
          {n.name}
        </button>
      ))}
    </div>
  ),
}));

import { Route } from "@/routes/knowledge";

const Page = (Route as unknown as { component: React.ComponentType }).component;

const ROOT: Concept = {
  id: "root-1",
  name: "Physics",
  slug: "physics",
  description: "Physics is the study of matter and energy.",
  times_expanded: 1,
  connections: 3,
  created_at: "2026-01-01T00:00:00Z",
};

const CHILD: Concept = {
  ...ROOT,
  id: "child-1",
  name: "Quantum Mechanics",
  slug: "quantum-mechanics",
  description: "",
  times_expanded: 0,
};

const GRAPH: GraphPayload = {
  nodes: [ROOT, CHILD],
  edges: [
    {
      id: "e1",
      source: { id: ROOT.id, name: ROOT.name, slug: ROOT.slug },
      target: { id: CHILD.id, name: CHILD.name, slug: CHILD.slug },
      relation: "has_subfield",
      weight: 0.9,
      times_seen: 1,
    },
  ],
};

const ROOT_DETAIL: ConceptDetail = { ...ROOT, outgoing: GRAPH.edges, incoming: [] };
const CHILD_DETAIL: ConceptDetail = { ...CHILD, outgoing: [], incoming: GRAPH.edges };

function baseHandlers() {
  return [
    http.get(`${BASE}/api/knowledge/concepts/`, () =>
      HttpResponse.json({ count: 2, next: null, previous: null, results: [ROOT, CHILD] })
    ),
    http.get(`${BASE}/api/knowledge/concepts/:id/graph/`, () => HttpResponse.json(GRAPH)),
    http.get(`${BASE}/api/knowledge/concepts/:id/`, ({ params }) =>
      HttpResponse.json(params.id === CHILD.id ? CHILD_DETAIL : ROOT_DETAIL)
    ),
  ];
}

beforeEach(() => {
  server.use(...baseHandlers());
  // The graph defaults to the tree layout, whose ECharts series is a single nested root
  // (no flat per-node entries for the mock to expose). These tests drive node-level
  // interactions, so start them in the force layout (as a returning user who picked it would)
  // where each concept renders as its own clickable node.
  localStorage.setItem("knowledge.layoutMode.v1", "force");
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("KnowledgePage", () => {
  it("renders concepts and the graph", async () => {
    renderWithQuery(<Page />);
    // the Build overlay panel is present
    expect(await screen.findByText("Build")).toBeInTheDocument();
    // the Concepts list heading is present
    expect(await screen.findByText(/Concepts/)).toBeInTheDocument();
    // graph renders both nodes
    await waitFor(() => expect(screen.getByTestId("concept-graph")).toBeInTheDocument());
    expect(screen.getAllByText("Physics").length).toBeGreaterThan(0);
  });

  it("ranks the concept table by reach and shows each reach count", async () => {
    // The table requests ?ordering=-reach; the server returns reach-ranked rows. The badge shows
    // the reach value, not the connection count.
    server.use(
      http.get(`${BASE}/api/knowledge/concepts/`, ({ request }) => {
        const ordering = new URL(request.url).searchParams.get("ordering");
        const ranked = [
          { ...ROOT, reach: 7 },
          { ...CHILD, reach: 2 },
        ];
        const results = ordering === "-reach" ? ranked : [ROOT, CHILD];
        return HttpResponse.json({ count: 2, next: null, previous: null, results });
      })
    );
    renderWithQuery(<Page />);
    expect(await screen.findByText("Concepts (highest reach first)")).toBeInTheDocument();
    // ROOT's reach (7) is shown in its row badge (title carries both reach and connections).
    // getAll because both the concept table and the auto-expand hub preview list it.
    expect((await screen.findAllByTitle("reach 7 (3 connections)")).length).toBeGreaterThan(0);
  });

  it("shows only the top 5 concepts in the table", async () => {
    // Six reach-ranked rows come back; the table renders only the first five.
    const many = Array.from({ length: 6 }, (_, i) => ({
      ...ROOT,
      id: `r${i}`,
      name: `Concept ${i}`,
      slug: `concept-${i}`,
      reach: 6 - i, // already reach-desc: Concept 0 highest ... Concept 5 lowest
    }));
    server.use(
      http.get(`${BASE}/api/knowledge/concepts/`, () =>
        HttpResponse.json({ count: 6, next: null, previous: null, results: many })
      )
    );
    renderWithQuery(<Page />);
    // Concept 0 (highest reach) renders; getAll because the hub preview lists it too.
    expect((await screen.findAllByText("Concept 0")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Concept 4").length).toBeGreaterThan(0); // 5th still in
    // The 6th (lowest reach) is sliced out of the top-5 list everywhere.
    expect(screen.queryByText("Concept 5")).not.toBeInTheDocument();
  });

  it("validates the create-node form", async () => {
    renderWithQuery(<Page />);
    fireEvent.click(await screen.findByRole("button", { name: "Create concept" }));
    expect(await screen.findByText("Name is required")).toBeInTheDocument();
  });

  it("creates a new concept", async () => {
    let posted: unknown = null;
    server.use(
      http.post(`${BASE}/api/knowledge/concepts/`, async ({ request }) => {
        posted = await request.json();
        return HttpResponse.json(ROOT, { status: 201 });
      })
    );
    renderWithQuery(<Page />);
    fireEvent.change(await screen.findByLabelText("New concept"), {
      target: { value: "Physics" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create concept" }));
    await waitFor(() => expect(posted).toEqual({ name: "Physics" }));
  });

  it("sends the negative_description seed when provided", async () => {
    let posted: unknown = null;
    server.use(
      http.post(`${BASE}/api/knowledge/concepts/`, async ({ request }) => {
        posted = await request.json();
        return HttpResponse.json(ROOT, { status: 201 });
      })
    );
    renderWithQuery(<Page />);
    fireEvent.change(await screen.findByLabelText("New concept"), {
      target: { value: "pop" },
    });
    fireEvent.change(
      screen.getByLabelText("Not to be confused with (optional)"),
      { target: { value: "Not the stack pop()." } }
    );
    fireEvent.click(screen.getByRole("button", { name: "Create concept" }));
    await waitFor(() =>
      expect(posted).toEqual({ name: "pop", negative_description: "Not the stack pop()." })
    );
  });

  it("expands a node to 1st degree", async () => {
    let expandBody: unknown = null;
    let expandedId: string | undefined;
    server.use(
      http.post(`${BASE}/api/knowledge/concepts/:id/expand/`, async ({ request, params }) => {
        expandBody = await request.json();
        expandedId = params.id as string;
        return HttpResponse.json(
          { status: "started", concept: params.id, max_depth: 1 },
          { status: 202 }
        );
      })
    );
    renderWithQuery(<Page />);
    await waitFor(() => expect(screen.getByTestId("concept-graph")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId(`concept-node-${CHILD.id}`));
    const expandBtn = await screen.findByRole("button", { name: "1st degree" });
    await waitFor(() => expect(expandBtn).not.toBeDisabled());
    fireEvent.click(expandBtn);
    await waitFor(() => expect(expandBody).toEqual({ max_depth: 1, force: true }));
    expect(expandedId).toBe(CHILD.id);
    expect(await screen.findByText("Expansion started.")).toBeInTheDocument();
  });

  it("expands a node to 3rd degree", async () => {
    let expandBody: unknown = null;
    server.use(
      http.post(`${BASE}/api/knowledge/concepts/:id/expand/`, async ({ request, params }) => {
        expandBody = await request.json();
        return HttpResponse.json(
          { status: "started", concept: params.id, max_depth: 3 },
          { status: 202 }
        );
      })
    );
    renderWithQuery(<Page />);
    await waitFor(() => expect(screen.getByTestId("concept-graph")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId(`concept-node-${CHILD.id}`));
    const expandBtn = await screen.findByRole("button", { name: "3rd degree" });
    await waitFor(() => expect(expandBtn).not.toBeDisabled());
    fireEvent.click(expandBtn);
    await waitFor(() => expect(expandBody).toEqual({ max_depth: 3, force: true }));
  });

  it("reranks-and-prunes every hub graph-wide and reports the queued count", async () => {
    let calledAll = false;
    server.use(
      http.post(`${BASE}/api/knowledge/rerank-all/`, () => {
        calledAll = true;
        return HttpResponse.json({ status: "started", queued: 3 }, { status: 202 });
      })
    );
    renderWithQuery(<Page />);
    await waitFor(() => expect(screen.getByTestId("concept-graph")).toBeInTheDocument());
    // The rerank button is graph-wide and lives next to "Reduce edges" in the Build panel.
    fireEvent.click(await screen.findByRole("button", { name: "Rerank & prune edges" }));
    await waitFor(() => expect(calledAll).toBe(true));
    expect(await screen.findByText(/Rerank queued for 3 hubs/)).toBeInTheDocument();
  });

  it("reduces transitive edges and reports the removed count", async () => {
    let reduced = false;
    server.use(
      http.post(`${BASE}/api/knowledge/edges/reduce/`, () => {
        reduced = true;
        return HttpResponse.json({ status: "reduced", removed: 4 });
      })
    );
    renderWithQuery(<Page />);
    await waitFor(() => expect(screen.getByTestId("concept-graph")).toBeInTheDocument());
    fireEvent.click(await screen.findByRole("button", { name: "Reduce edges" }));
    await waitFor(() => expect(reduced).toBe(true));
    expect(await screen.findByText(/Removed 4 redundant edges/)).toBeInTheDocument();
  });

  it("refetches concepts after an expansion so connection counts update", async () => {
    // Expansion runs async on the backend; the new connection counts/edges land after the
    // POST returns. The mutation must invalidate the concept list so its badges refresh
    // instead of going stale until a manual reload.
    let listCalls = 0;
    server.use(
      http.get(`${BASE}/api/knowledge/concepts/`, () => {
        listCalls += 1;
        return HttpResponse.json({ count: 2, next: null, previous: null, results: [ROOT, CHILD] });
      }),
      http.post(`${BASE}/api/knowledge/concepts/:id/expand/`, ({ params }) =>
        HttpResponse.json({ status: "started", concept: params.id, max_depth: 1 }, { status: 202 })
      )
    );
    renderWithQuery(<Page />);
    await waitFor(() => expect(screen.getByTestId("concept-graph")).toBeInTheDocument());
    const callsBeforeExpand = listCalls;

    fireEvent.click(screen.getByTestId(`concept-node-${CHILD.id}`));
    const expandBtn = await screen.findByRole("button", { name: "1st degree" });
    await waitFor(() => expect(expandBtn).not.toBeDisabled());
    fireEvent.click(expandBtn);

    // The expansion mutation invalidates the concept list -> it is fetched again.
    await waitFor(() => expect(listCalls).toBeGreaterThan(callsBeforeExpand));
  });

  it("fades out 1st degree for an already-expanded node but keeps 2nd/3rd", async () => {
    renderWithQuery(<Page />);
    // root detail loads first (selected defaults to root, times_expanded = 1)
    await screen.findByText("Physics is the study of matter and energy.");
    // 1st degree only expands the node itself, which is already done -> disabled once the
    // subgraph (which the ball check reads) has loaded.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "1st degree" })).toBeDisabled()
    );
    // 2nd/3rd reach the still-unexpanded neighbor (CHILD) within their ball, so they stay live.
    expect(screen.getByRole("button", { name: "2nd degree" })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "3rd degree" })).not.toBeDisabled();
  });

  it("fades out every degree once the whole ball is already expanded", async () => {
    // ROOT and its only neighbor are both expanded -> nothing unexpanded within reach, so
    // 1st, 2nd, and 3rd degree all fade out (not just 1st).
    const expandedGraph: GraphPayload = {
      nodes: [ROOT, { ...CHILD, times_expanded: 1 }],
      edges: GRAPH.edges,
    };
    server.use(
      http.get(`${BASE}/api/knowledge/concepts/:id/graph/`, () =>
        HttpResponse.json(expandedGraph)
      ),
      http.get(`${BASE}/api/knowledge/concepts/:id/`, ({ params }) =>
        HttpResponse.json(
          params.id === CHILD.id ? { ...CHILD_DETAIL, times_expanded: 1 } : ROOT_DETAIL
        )
      )
    );
    renderWithQuery(<Page />);
    await screen.findByText("Physics is the study of matter and energy.");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "1st degree" })).toBeDisabled()
    );
    expect(screen.getByRole("button", { name: "2nd degree" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "3rd degree" })).toBeDisabled();
  });

  it("keeps a degree live when only a deeper ring is still unexpanded", async () => {
    // ROOT(expanded) -> CHILD(expanded) -> GRANDCHILD(unexpanded). Within 0 hops (1st) and 1 hop
    // (2nd) everything is expanded, but the unexpanded GRANDCHILD is 2 hops out, so only 3rd
    // degree still has work - proving the fade is per-degree, not all-or-nothing.
    const grandchild: Concept = {
      ...CHILD,
      id: "gc-1",
      name: "Wavefunction",
      slug: "wavefunction",
      times_expanded: 0,
    };
    const chainGraph: GraphPayload = {
      nodes: [ROOT, { ...CHILD, times_expanded: 1 }, grandchild],
      edges: [
        ...GRAPH.edges,
        {
          id: "e2",
          source: { id: CHILD.id, name: CHILD.name, slug: CHILD.slug },
          target: { id: grandchild.id, name: grandchild.name, slug: grandchild.slug },
          relation: "has_subfield",
          weight: 0.9,
          times_seen: 1,
        },
      ],
    };
    server.use(
      http.get(`${BASE}/api/knowledge/concepts/:id/graph/`, () => HttpResponse.json(chainGraph)),
      http.get(`${BASE}/api/knowledge/concepts/:id/`, ({ params }) =>
        HttpResponse.json(
          params.id === CHILD.id ? { ...CHILD_DETAIL, times_expanded: 1 } : ROOT_DETAIL
        )
      )
    );
    renderWithQuery(<Page />);
    await screen.findByText("Physics is the study of matter and energy.");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "2nd degree" })).toBeDisabled()
    );
    expect(screen.getByRole("button", { name: "1st degree" })).toBeDisabled();
    // 3rd degree's ball reaches the unexpanded grandchild two hops out -> still live.
    expect(screen.getByRole("button", { name: "3rd degree" })).not.toBeDisabled();
  });

  it("auto-expand seeds the top-5 hub crawl at depth 3", async () => {
    // The backend picks the top-5 most-connected hubs; the button just POSTs {max_depth}. The
    // crawl then grows their frontier ring by ring (depth 1, then 2, then 3) server-side.
    let body: unknown = null;
    server.use(
      http.post(`${BASE}/api/knowledge/expansion/auto/`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(
          { status: "started", hubs: ["root-1"], max_depth: 3 },
          { status: 202 }
        );
      })
    );
    renderWithQuery(<Page />);
    await waitFor(() => expect(screen.getByTestId("concept-graph")).toBeInTheDocument());
    fireEvent.click(await screen.findByRole("button", { name: "Auto-expand top 5" }));
    await waitFor(() => expect(body).toEqual({ max_depth: 3 }));
    expect(await screen.findByText(/Crawling 1 hub to depth 3/)).toBeInTheDocument();
  });

  it("clear queue calls the clear endpoint and reports the purge count", async () => {
    let cleared = false;
    server.use(
      http.post(`${BASE}/api/knowledge/expansion/clear/`, () => {
        cleared = true;
        return HttpResponse.json({ status: "cleared", purged: 12, epoch: 3 });
      })
    );
    renderWithQuery(<Page />);
    await waitFor(() => expect(screen.getByTestId("concept-graph")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Clear queue/ }));
    await waitFor(() => expect(cleared).toBe(true));
    expect(await screen.findByText(/purged 12 queued tasks/)).toBeInTheDocument();
  });

  it("requests a filtered concept list when searching", async () => {
    const searches: (string | null)[] = [];
    server.use(
      http.get(`${BASE}/api/knowledge/concepts/`, ({ request }) => {
        searches.push(new URL(request.url).searchParams.get("search"));
        return HttpResponse.json({ count: 2, next: null, previous: null, results: [ROOT, CHILD] });
      })
    );
    renderWithQuery(<Page />);
    fireEvent.change(await screen.findByPlaceholderText("Search concepts..."), {
      target: { value: "quantum" },
    });
    await waitFor(() => expect(searches).toContain("quantum"));
  });

  it("switches the graph root when a concept is picked from the list", async () => {
    const graphIds: string[] = [];
    server.use(
      http.get(`${BASE}/api/knowledge/concepts/:id/graph/`, ({ params }) => {
        graphIds.push(params.id as string);
        return HttpResponse.json(GRAPH);
      })
    );
    renderWithQuery(<Page />);
    // with no explicit root, the first concept (ROOT) is the default viewing root
    await waitFor(() => expect(graphIds).toContain(ROOT.id));
    // the CHILD list entry carries a "new" badge (times_expanded === 0); clicking it re-roots
    fireEvent.click(await screen.findByRole("button", { name: /Quantum Mechanics new/i }));
    await waitFor(() => expect(graphIds).toContain(CHILD.id));
  });

  it("re-roots the graph on the clicked node to show its connections", async () => {
    const graphIds: string[] = [];
    server.use(
      http.get(`${BASE}/api/knowledge/concepts/:id/graph/`, ({ params }) => {
        graphIds.push(params.id as string);
        return HttpResponse.json(GRAPH);
      })
    );
    renderWithQuery(<Page />);
    // default viewing root is ROOT; clicking the CHILD node in the canvas re-centres on it
    await waitFor(() => expect(graphIds).toContain(ROOT.id));
    fireEvent.click(await screen.findByTestId(`concept-node-${CHILD.id}`));
    await waitFor(() => expect(graphIds).toContain(CHILD.id));
  });

  it("deletes the selected node after confirmation", async () => {
    let deletedId: string | undefined;
    server.use(
      http.delete(`${BASE}/api/knowledge/concepts/:id/`, ({ params }) => {
        deletedId = params.id as string;
        return new HttpResponse(null, { status: 204 });
      })
    );
    const confirm = vi.fn().mockReturnValue(true);
    vi.stubGlobal("confirm", confirm);
    renderWithQuery(<Page />);
    // root detail is selected by default
    await screen.findByText("Physics is the study of matter and energy.");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(confirm).toHaveBeenCalled();
    await waitFor(() => expect(deletedId).toBe(ROOT.id));
  });

  it("does not delete when confirmation is dismissed", async () => {
    let called = false;
    server.use(
      http.delete(`${BASE}/api/knowledge/concepts/:id/`, () => {
        called = true;
        return new HttpResponse(null, { status: 204 });
      })
    );
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(false));
    renderWithQuery(<Page />);
    await screen.findByText("Physics is the study of matter and energy.");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    // give any (unexpected) request a chance to fire
    await new Promise((r) => setTimeout(r, 50));
    expect(called).toBe(false);
  });

  it("minimises and restores an overlay panel", async () => {
    renderWithQuery(<Page />);
    // the Build panel's contents (Concepts list) are visible by default
    expect(await screen.findByText(/Concepts/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Minimise Build" }));
    expect(screen.queryByText(/Concepts/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Expand Build" }));
    expect(await screen.findByText(/Concepts/)).toBeInTheDocument();
  });

  it("the View depth slider limits how many hops out from the selected node are shown", async () => {
    // A chain root -> child -> grandchild, so grandchild is two hops from the (default-
    // selected) root. The graph endpoint returns the whole chain regardless of hops; the
    // View depth slider drives the client-side neighborhood filter in ConceptGraph.
    const GRANDCHILD: Concept = {
      ...CHILD,
      id: "grandchild-1",
      name: "Quantum Field Theory",
      slug: "quantum-field-theory",
    };
    const CHAIN: GraphPayload = {
      nodes: [ROOT, CHILD, GRANDCHILD],
      edges: [
        ...GRAPH.edges,
        {
          id: "e2",
          source: { id: CHILD.id, name: CHILD.name, slug: CHILD.slug },
          target: { id: GRANDCHILD.id, name: GRANDCHILD.name, slug: GRANDCHILD.slug },
          relation: "has_subfield",
          weight: 0.9,
          times_seen: 1,
        },
      ],
    };
    server.use(
      http.get(`${BASE}/api/knowledge/concepts/:id/graph/`, () => HttpResponse.json(CHAIN))
    );

    renderWithQuery(<Page />);
    // Default depth is 2: every node in the two-hop neighborhood of the root is rendered.
    await waitFor(() =>
      expect(screen.getByTestId("concept-node-grandchild-1")).toBeInTheDocument()
    );

    // Drop the View depth to 1: after the refetch settles the direct child + root remain but
    // the two-hop grandchild is filtered out of the one-hop neighborhood.
    fireEvent.change(screen.getByRole("slider"), { target: { value: "1" } });
    await waitFor(() => {
      expect(screen.getByTestId("concept-node-child-1")).toBeInTheDocument();
      expect(screen.queryByTestId("concept-node-grandchild-1")).not.toBeInTheDocument();
    });
    expect(screen.getByTestId("concept-node-root-1")).toBeInTheDocument();
  });
});
