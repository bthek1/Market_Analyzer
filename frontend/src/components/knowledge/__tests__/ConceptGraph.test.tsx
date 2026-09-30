import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { GraphPayload } from "@/types/knowledge";

// ECharts renders to canvas (unsupported in jsdom). Mock it to a DOM stand-in that
// exposes one button per graph node so node interactions remain testable, and capture
// the last `option` so we can assert how the chart was configured.
interface MockNode {
  id: string;
  name: string;
  _frontier: boolean;
}
interface MockEvents {
  click?: (p: { dataType: string; data: MockNode }) => void;
  dblclick?: (p: { dataType: string; data: MockNode }) => void;
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const captured = vi.hoisted(() => ({ option: null as any }));
vi.mock("echarts-for-react", () => ({
  default: ({
    option,
    onEvents,
  }: {
    option: { series: { data: MockNode[] }[] };
    onEvents?: MockEvents;
  }) => {
    captured.option = option;
    return (
      <div data-testid="echart">
        {option.series[0].data.map((n) => (
          <button
            key={n.id}
            type="button"
            data-testid={`concept-node-${n.id}`}
            data-frontier={n._frontier ? "true" : "false"}
            onClick={() => onEvents?.click?.({ dataType: "node", data: n })}
            onDoubleClick={() => onEvents?.dblclick?.({ dataType: "node", data: n })}
          >
            {n.name}
          </button>
        ))}
      </div>
    );
  },
}));

import { ConceptGraph } from "@/components/knowledge/ConceptGraph";

function makeGraph(): GraphPayload {
  return {
    nodes: [
      {
        id: "n1",
        name: "Physics",
        slug: "physics",
        description: "",
        times_expanded: 1,
        connections: 1,
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "n2",
        name: "Quantum Mechanics",
        slug: "quantum-mechanics",
        description: "",
        times_expanded: 0,
        connections: 1,
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
    edges: [
      {
        id: "e1",
        source: { id: "n1", name: "Physics", slug: "physics" },
        target: { id: "n2", name: "Quantum Mechanics", slug: "quantum-mechanics" },
        relation: "has_subfield",
        weight: 0.9,
        times_seen: 1,
      },
    ],
  };
}

describe("ConceptGraph", () => {
  // The component now defaults to the tree layout, whose ECharts series is a single nested
  // root (the mock exposes no flat per-node buttons for it). These tests assert the flat
  // force-graph series, so seed the persisted layout to force - as a returning user who
  // picked it would have. The dedicated "defaults to the tree layout" test clears this first.
  beforeEach(() => {
    localStorage.setItem("knowledge.layoutMode.v1", "force");
  });
  afterEach(() => {
    localStorage.clear();
  });

  it("defaults to the tree layout when nothing is persisted", () => {
    localStorage.clear();
    render(<ConceptGraph graph={makeGraph()} />);
    expect(captured.option.series[0].type).toBe("tree");
    expect(screen.getByRole("button", { name: "Tree" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });

  it("renders an empty state with no nodes", () => {
    render(<ConceptGraph graph={{ nodes: [], edges: [] }} />);
    expect(screen.getByTestId("concept-graph-empty")).toBeInTheDocument();
  });

  it("renders nodes and edges", () => {
    render(<ConceptGraph graph={makeGraph()} />);
    expect(screen.getByTestId("concept-graph")).toBeInTheDocument();
    expect(screen.getByText("Physics")).toBeInTheDocument();
    expect(screen.getByText("Quantum Mechanics")).toBeInTheDocument();
  });

  it("calls onSelect when a node is clicked", () => {
    const onSelect = vi.fn();
    render(<ConceptGraph graph={makeGraph()} onSelect={onSelect} />);
    fireEvent.click(screen.getByTestId("concept-node-n2"));
    expect(onSelect).toHaveBeenCalledWith("n2");
  });

  it("calls onExpand when a node is double-clicked", () => {
    const onExpand = vi.fn();
    render(<ConceptGraph graph={makeGraph()} onExpand={onExpand} />);
    fireEvent.doubleClick(screen.getByTestId("concept-node-n2"));
    expect(onExpand).toHaveBeenCalledWith("n2");
  });

  it("marks unexpanded nodes as frontier and expanded nodes as not", () => {
    render(<ConceptGraph graph={makeGraph()} />);
    // n1 is expanded (times_expanded=1), n2 is still a frontier node (times_expanded=0).
    expect(screen.getByTestId("concept-node-n1")).toHaveAttribute("data-frontier", "false");
    expect(screen.getByTestId("concept-node-n2")).toHaveAttribute("data-frontier", "true");
  });

  it("builds a roamable force-directed graph series", () => {
    render(<ConceptGraph graph={makeGraph()} />);
    const series = captured.option.series[0];
    expect(series.type).toBe("graph");
    expect(series.layout).toBe("force");
    expect(series.roam).toBe(true);
    expect(series.data).toHaveLength(2);
    // the graph is start-point agnostic: no depth-based categories
    expect(series.categories).toBeUndefined();
  });

  it("styles frontier nodes hollow with a dashed border", () => {
    render(<ConceptGraph graph={makeGraph()} />);
    const data = captured.option.series[0].data as Array<{
      id: string;
      itemStyle: { color: string; borderType: string };
    }>;
    const frontier = data.find((d) => d.id === "n2")!;
    const expanded = data.find((d) => d.id === "n1")!;
    // Frontier fill is a pale tint (hollow look) - NOT pure white, which is invisible on canvas.
    expect(frontier.itemStyle.color).not.toBe("#ffffff");
    expect(frontier.itemStyle.color).toMatch(/^rgb\(/);
    expect(frontier.itemStyle.borderType).toBe("dashed");
    expect(expanded.itemStyle.borderType).toBe("solid");
  });

  it("emphasises the selected node and scales edge width by weight", () => {
    render(<ConceptGraph graph={makeGraph()} selectedId="n1" />);
    const series = captured.option.series[0];
    const selected = series.data.find((d: { id: string }) => d.id === "n1");
    const other = series.data.find((d: { id: string }) => d.id === "n2");
    expect(selected.symbolSize).toBeGreaterThan(other.symbolSize);
    // edge weight 0.9 -> width 1 + 0.9*3 = 3.7
    expect(series.links[0].lineStyle.width).toBeCloseTo(3.7);
  });

  // Two expanded nodes (so fill colour, not the hollow frontier white) with different degrees.
  function makeDegreeGraph(): GraphPayload {
    const base = {
      slug: "x",
      description: "",
      times_expanded: 1,
      created_at: "2026-01-01T00:00:00Z",
    };
    return {
      nodes: [
        { ...base, id: "hub", name: "Hub", slug: "hub", connections: 8 },
        { ...base, id: "leaf", name: "Leaf", slug: "leaf", connections: 1 },
      ],
      edges: [],
    };
  }

  const redChannel = (rgb: string) => Number(rgb.match(/\d+/g)![0]);
  const blueChannel = (rgb: string) => Number(rgb.match(/\d+/g)![2]);

  it("colours higher-degree nodes redder and lower-degree nodes bluer", () => {
    render(<ConceptGraph graph={makeDegreeGraph()} />);
    const data = captured.option.series[0].data as Array<{
      id: string;
      itemStyle: { color: string };
    }>;
    const hub = data.find((d) => d.id === "hub")!;
    const leaf = data.find((d) => d.id === "leaf")!;
    expect(redChannel(hub.itemStyle.color)).toBeGreaterThan(redChannel(leaf.itemStyle.color));
    expect(blueChannel(hub.itemStyle.color)).toBeLessThan(blueChannel(leaf.itemStyle.color));
  });

  it("scales node size with the connection count", () => {
    render(<ConceptGraph graph={makeDegreeGraph()} />);
    const data = captured.option.series[0].data as Array<{ id: string; symbolSize: number }>;
    const hub = data.find((d) => d.id === "hub")!;
    const leaf = data.find((d) => d.id === "leaf")!;
    expect(hub.symbolSize).toBeGreaterThan(leaf.symbolSize);
  });

  it("colours and scales by structural reach (overriding raw connection count)", () => {
    // `deep` has FEW neighbours but high recursive reach; `wide` has MANY neighbours but no
    // downstream structure. `deep` must read as the larger/redder node - reach wins over degree.
    const base = {
      slug: "x",
      description: "",
      times_expanded: 1,
      created_at: "2026-01-01T00:00:00Z",
    };
    const graph: GraphPayload = {
      nodes: [
        { ...base, id: "deep", name: "Deep", slug: "deep", connections: 1, reach: 12 },
        { ...base, id: "wide", name: "Wide", slug: "wide", connections: 9, reach: 0 },
      ],
      edges: [],
    };
    render(<ConceptGraph graph={graph} />);
    const data = captured.option.series[0].data as Array<{
      id: string;
      symbolSize: number;
      itemStyle: { color: string };
    }>;
    const deep = data.find((d) => d.id === "deep")!;
    const wide = data.find((d) => d.id === "wide")!;
    expect(redChannel(deep.itemStyle.color)).toBeGreaterThan(redChannel(wide.itemStyle.color));
    expect(deep.symbolSize).toBeGreaterThan(wide.symbolSize);
  });

  it("tints a frontier node's fill so it stays visible (not white-on-white)", () => {
    render(<ConceptGraph graph={makeGraph()} />);
    const frontier = (captured.option.series[0].data as Array<{
      id: string;
      itemStyle: { color: string; borderColor: string };
    }>).find((d) => d.id === "n2")!;
    const fill = frontier.itemStyle.color;
    const ring = frontier.itemStyle.borderColor;
    expect(fill).not.toBe("#ffffff"); // visible pale tint, not invisible white
    expect(ring).not.toBe("#ffffff"); // coloured ring
    // The fill is the ring's heat colour blended toward white: paler on every channel, but not
    // pure white - so it reads as "hollow / not yet expanded" while staying visible.
    const channels = (c: string) => c.match(/\d+/g)!.map(Number);
    const [fr, fg, fb] = channels(fill);
    const [rr, rg, rb] = channels(ring);
    expect(fr).toBeGreaterThanOrEqual(rr);
    expect(fg).toBeGreaterThanOrEqual(rg);
    expect(fb).toBeGreaterThanOrEqual(rb);
    expect(Math.min(fr, fg, fb)).toBeLessThan(255); // not pure white
  });

  it("switches to a layered hierarchy layout with fixed positions when toggled", () => {
    render(<ConceptGraph graph={makeGraph()} />);
    // Force layout (seeded as the persisted choice in beforeEach).
    expect(captured.option.series[0].layout).toBe("force");
    fireEvent.click(screen.getByRole("button", { name: "Hierarchy" }));
    const series = captured.option.series[0];
    // ECharts places nodes itself via computed positions in hierarchy mode.
    expect(series.layout).toBe("none");
    const data = series.data as Array<{ id: string; x: number; y: number; fixed: boolean }>;
    // edge is "n1 has_subfield n2" -> n1 (the broader field) is the parent, drawn on top
    // (smaller y), n2 the child below; both are pinned to their computed positions.
    const parent = data.find((d) => d.id === "n1")!;
    const child = data.find((d) => d.id === "n2")!;
    expect(parent.fixed).toBe(true);
    expect(child.fixed).toBe(true);
    expect(parent.y).toBeLessThan(child.y);
  });

  it("shows the structural reach in the node tooltip", () => {
    render(<ConceptGraph graph={makeDegreeGraph()} />);
    const html = captured.option.tooltip.formatter({
      dataType: "node",
      data: { name: "Hub", _weight: 8 },
    });
    expect(html).toContain("Hub");
    expect(html).toContain("reach 8");
  });

  it("shows the negative description (what it is NOT) in the node tooltip", () => {
    render(<ConceptGraph graph={makeDegreeGraph()} />);
    const html = captured.option.tooltip.formatter({
      dataType: "node",
      data: { name: "Pop", _weight: 3, _desc: "music genre", _negative: "not the stack op" },
    });
    expect(html).toContain("music genre");
    expect(html).toContain("Not: not the stack op");
  });

  it("colours each edge by its relation type", () => {
    render(<ConceptGraph graph={makeGraph()} />);
    // makeGraph's single edge is `has_subfield` -> its mapped blue.
    expect(captured.option.series[0].links[0].lineStyle.color).toBe("#2563eb");
  });

  // A single prerequisite_for edge n1 -> n2: n1 is the foundation (drawn on top).
  function makePrereqGraph(): GraphPayload {
    const g = makeGraph();
    g.edges[0].relation = "prerequisite_for";
    return g;
  }

  it("colours a prerequisite_for edge red", () => {
    render(<ConceptGraph graph={makePrereqGraph()} />);
    expect(captured.option.series[0].links[0].lineStyle.color).toBe("#dc2626");
  });

  it("treats prerequisite_for as a backbone edge with the source as the foundation", () => {
    render(<ConceptGraph graph={makePrereqGraph()} />);
    fireEvent.click(screen.getByRole("button", { name: "Hierarchy" }));
    const data = captured.option.series[0].data as Array<{ id: string; y: number }>;
    // edge is "n1 prerequisite_for n2" -> n1 (the foundation) is the parent, drawn on top.
    const foundation = data.find((d) => d.id === "n1")!;
    const dependent = data.find((d) => d.id === "n2")!;
    expect(foundation.y).toBeLessThan(dependent.y);
  });

  // Edges persisted before the five->three relation reduction may still carry a legacy
  // value like `uses`. The UI must degrade gracefully rather than crash or mis-colour.
  function makeLegacyGraph(): GraphPayload {
    const g = makeGraph();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (g.edges[0] as any).relation = "uses";
    return g;
  }

  it("renders a legacy relation value with the neutral fallback colour", () => {
    render(<ConceptGraph graph={makeLegacyGraph()} />);
    expect(screen.getByTestId("concept-graph")).toBeInTheDocument();
    // Unknown relation -> neutral grey, not one of the mapped relation colours.
    expect(captured.option.series[0].links[0].lineStyle.color).toBe("#94a3b8");
  });

  // A chain n1 - n2 - n3 so n3 is two hops from n1, for the depth-filter tests.
  function makeChainGraph(): GraphPayload {
    const base = {
      slug: "x",
      description: "",
      times_expanded: 1,
      connections: 2,
      created_at: "2026-01-01T00:00:00Z",
    };
    return {
      nodes: [
        { ...base, id: "n1", name: "One", slug: "one" },
        { ...base, id: "n2", name: "Two", slug: "two" },
        { ...base, id: "n3", name: "Three", slug: "three" },
      ],
      edges: [
        {
          id: "e1",
          source: { id: "n1", name: "One", slug: "one" },
          target: { id: "n2", name: "Two", slug: "two" },
          relation: "has_subfield",
          weight: 0.5,
          times_seen: 1,
        },
        {
          id: "e2",
          source: { id: "n2", name: "Two", slug: "two" },
          target: { id: "n3", name: "Three", slug: "three" },
          relation: "has_subfield",
          weight: 0.5,
          times_seen: 1,
        },
      ],
    };
  }

  it("at depth 1 shows only the selected node and its direct neighbors", () => {
    render(<ConceptGraph graph={makeChainGraph()} selectedId="n1" depth={1} />);
    const ids = (captured.option.series[0].data as Array<{ id: string }>).map((d) => d.id);
    expect(ids).toContain("n1");
    expect(ids).toContain("n2");
    // n3 is two hops away, so it is hidden at depth 1.
    expect(ids).not.toContain("n3");
  });

  it("at depth 2 also shows the neighbors of the neighbors", () => {
    render(<ConceptGraph graph={makeChainGraph()} selectedId="n1" depth={2} />);
    const ids = (captured.option.series[0].data as Array<{ id: string }>).map((d) => d.id);
    expect(ids).toEqual(expect.arrayContaining(["n1", "n2", "n3"]));
  });

  it("shows the whole graph when no node is selected", () => {
    render(<ConceptGraph graph={makeChainGraph()} depth={1} />);
    expect(captured.option.series[0].data).toHaveLength(3);
  });

  it("re-roots the tree on the selected node with a faded ancestor breadcrumb spine", () => {
    // makeGraph: n1 -has_subfield-> n2, so n1 is n2's parent. Selecting n2 focuses on it and
    // draws n1 above it as a single-child, half-opacity breadcrumb leading down to n2.
    render(<ConceptGraph graph={makeGraph()} selectedId="n2" />);
    fireEvent.click(screen.getByRole("button", { name: "Tree" }));
    const root = captured.option.series[0].data[0];
    expect(root.name).toBe("n1"); // ancestor at the top of the spine
    expect(root.itemStyle.opacity).toBeCloseTo(0.5); // faded breadcrumb
    expect(root.children).toHaveLength(1);
    expect(root.children[0].name).toBe("n2"); // the focused node below it
  });

  it("re-roots a focused multi-parent node under its single primary parent (no duplicate)", () => {
    // c has two parents p1 (primary) and p2; the tree keeps only the primary. Focusing c draws p1
    // as the faded breadcrumb above it - p2 is NOT shown (that is the hierarchy view's job) and c
    // is never duplicated.
    render(<ConceptGraph graph={makeMultiParentGraph()} selectedId="c" />);
    fireEvent.click(screen.getByRole("button", { name: "Tree" }));
    const root = captured.option.series[0].data[0];
    expect(root.name).toBe("p1"); // single primary-parent spine, no __root__ wrapper
    expect(root.children).toHaveLength(1);
    expect(root.children[0].name).toBe("c");
    expect(root.children[0].children).toHaveLength(0); // c has no further subtree
  });

  it("colours each tree edge by the relation joining a node to its parent", () => {
    render(<ConceptGraph graph={makeGraph()} selectedId="n2" />);
    fireEvent.click(screen.getByRole("button", { name: "Tree" }));
    // The edge from n1 down to n2 is `has_subfield` -> its mapped blue lives on the child node.
    const child = captured.option.series[0].data[0].children[0];
    expect(child.lineStyle.color).toBe("#2563eb");
  });

  it("makes tree subtrees collapsible/expandable on click", () => {
    render(<ConceptGraph graph={makeGraph()} selectedId="n2" />);
    fireEvent.click(screen.getByRole("button", { name: "Tree" }));
    expect(captured.option.series[0].expandAndCollapse).toBe(true);
  });

  // Two separate root concepts (p1, p2) that both have_subfield the same child c. c attaches to
  // one primary parent in the tree; the other parent is a non-primary backbone link.
  function makeMultiParentGraph(): GraphPayload {
    const base = {
      slug: "x",
      description: "",
      times_expanded: 1,
      connections: 1,
      created_at: "2026-01-01T00:00:00Z",
    };
    const edge = (id: string, s: string, sn: string, t: string, tn: string) => ({
      id,
      source: { id: s, name: sn, slug: s },
      target: { id: t, name: tn, slug: t },
      relation: "has_subfield" as const,
      weight: 0.8,
      times_seen: 1,
    });
    return {
      nodes: [
        { ...base, id: "p1", name: "P1", slug: "p1" },
        { ...base, id: "p2", name: "P2", slug: "p2" },
        { ...base, id: "c", name: "C", slug: "c" },
      ],
      edges: [edge("e1", "p1", "P1", "c", "C"), edge("e2", "p2", "P2", "c", "C")],
    };
  }

  it("gathers multiple roots under a hidden virtual root when nothing is selected", () => {
    render(<ConceptGraph graph={makeMultiParentGraph()} />);
    fireEvent.click(screen.getByRole("button", { name: "Tree" }));
    const root = captured.option.series[0].data[0];
    expect(root.name).toBe("__root__"); // hidden forest wrapper
    expect(root.symbolSize).toBe(0);
    expect(root.children.map((c: { name: string }) => c.name)).toEqual(["p1", "p2"]);
  });

  it("attaches a multi-parent node under a single primary parent, not duplicated", () => {
    render(<ConceptGraph graph={makeMultiParentGraph()} />);
    fireEvent.click(screen.getByRole("button", { name: "Tree" }));
    // c attaches to p1 (primary) only; the p2 -> c link is not drawn in the tree (no dashed
    // reference, no duplicate copy) - the hierarchy / sankey views render multi-parent structure.
    const [p1, p2] = captured.option.series[0].data[0].children;
    expect(p1.name).toBe("p1");
    expect(p1.children.map((k: { name: string }) => k.name)).toEqual(["c"]);
    expect(p2.name).toBe("p2");
    expect(p2.children).toHaveLength(0); // c is not duplicated under its non-primary parent
  });

  it("treats a legacy relation as a non-backbone cross-link in hierarchy mode", () => {
    render(<ConceptGraph graph={makeLegacyGraph()} />);
    fireEvent.click(screen.getByRole("button", { name: "Hierarchy" }));
    const data = captured.option.series[0].data as Array<{ id: string; y: number }>;
    // A non-directional (legacy/unknown) edge contributes no depth, so unlike `has_subfield`
    // both endpoints stay on the same level rather than parent-above-child.
    const n1 = data.find((d) => d.id === "n1")!;
    const n2 = data.find((d) => d.id === "n2")!;
    expect(n1.y).toBe(n2.y);
  });
});
