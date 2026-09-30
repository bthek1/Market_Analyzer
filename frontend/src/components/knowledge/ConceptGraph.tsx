/* eslint-disable react-hooks/refs --
   This component deliberately reads a position map (`posRef`) during render to PIN already
   laid-out nodes so the force graph does not reshuffle on every refetch/expand. The pinning
   is intentionally non-reactive (a ref, not state): positions are applied on the next
   data-driven render and updated from the chart's `finished` event. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactECharts from "echarts-for-react";
import type { Concept, ConceptEdge, GraphPayload, Relation } from "@/types/knowledge";

// Each relation type gets its own edge colour so the kind of link is readable at a glance.
const RELATION_COLORS: Record<Relation, string> = {
  has_subfield: "#2563eb", // blue
  prerequisite_for: "#dc2626", // red
};
const RELATION_LABELS: Record<Relation, string> = {
  has_subfield: "has subfield",
  prerequisite_for: "prerequisite for",
};

function relationColor(relation: string): string {
  return RELATION_COLORS[relation as Relation] ?? "#94a3b8";
}

/**
 * Shared tooltip body for a concept node across every layout (force / hierarchy / tree / sankey)
 * so a node reads identically everywhere: bold name + reach, then its description and its
 * negative description ("what it is NOT" - the homonym contrast).
 */
function nodeTooltipHtml(opts: {
  name: string;
  weight?: number;
  desc?: string;
  negative?: string;
}): string {
  let html = `<b>${opts.name}</b> (reach ${opts.weight ?? 0})`;
  if (opts.desc) html += `<br/>${opts.desc}`;
  if (opts.negative) html += `<br/><span style="opacity:.7">Not: ${opts.negative}</span>`;
  return html;
}

// Which endpoint of a directional relation is the PARENT (drawn higher up / smaller level).
// Both graph relations are directional; a legacy/unknown relation with no entry is treated as a
// non-backbone cross-link.
const HIERARCHY_PARENT: Partial<Record<Relation, "source" | "target">> = {
  has_subfield: "source", // a has_subfield b -> a is the broader field (on top)
  prerequisite_for: "source", // a prerequisite_for b -> a is the foundation (on top)
};

type Point = { x: number; y: number };

/**
 * The directional backbone shared by every layered view (hierarchy / tree / sankey). Every
 * directional edge is normalised to parent->child via HIERARCHY_PARENT (a legacy/unknown relation
 * with no entry is skipped as a cross-link). Cycles are broken by dropping DFS back-edges
 * (same trick as the backend's topological_waves) and each node's level is its longest path
 * from a root. Returned `liveParent(p, c)` reports whether a parent edge survived the break.
 */
interface Backbone {
  ids: string[];
  parents: Map<string, Set<string>>;
  level: Map<string, number>;
  liveParent: (parent: string, child: string) => boolean;
}

function buildBackbone(nodes: Concept[], edges: ConceptEdge[]): Backbone {
  const ids = nodes.map((n) => n.id);
  const idSet = new Set(ids);
  const children = new Map<string, Set<string>>(ids.map((id) => [id, new Set<string>()]));
  const parents = new Map<string, Set<string>>(ids.map((id) => [id, new Set<string>()]));

  for (const e of edges) {
    const dir = HIERARCHY_PARENT[e.relation];
    if (!dir) continue; // legacy/unknown relation -> cross-link, not part of the backbone
    const parent = dir === "source" ? e.source.id : e.target.id;
    const child = dir === "source" ? e.target.id : e.source.id;
    if (parent === child || !idSet.has(parent) || !idSet.has(child)) continue;
    children.get(parent)!.add(child);
    parents.get(child)!.add(parent);
  }

  // Break cycles with a DFS, recording back-edges (parent>child) so levelling terminates.
  const WHITE = 0;
  const GRAY = 1;
  const BLACK = 2;
  const color = new Map<string, number>(ids.map((id) => [id, WHITE]));
  const dropped = new Set<string>();
  const visit = (u: string) => {
    color.set(u, GRAY);
    for (const v of children.get(u)!) {
      const c = color.get(v);
      if (c === GRAY) dropped.add(`${u}>${v}`);
      else if (c === WHITE) visit(v);
    }
    color.set(u, BLACK);
  };
  ids.forEach((id) => {
    if (color.get(id) === WHITE) visit(id);
  });
  const liveParent = (p: string, c: string) => !dropped.has(`${p}>${c}`);

  // Longest-path level: 0 for roots, else max(surviving parent level) + 1.
  const level = new Map<string, number>();
  const computeLevel = (u: string): number => {
    const cached = level.get(u);
    if (cached !== undefined) return cached;
    level.set(u, 0); // guard against any residual cycle
    let lv = 0;
    for (const p of parents.get(u)!) {
      if (liveParent(p, u)) lv = Math.max(lv, computeLevel(p) + 1);
    }
    level.set(u, lv);
    return lv;
  };
  ids.forEach((id) => computeLevel(id));

  return { ids, parents, level, liveParent };
}

/**
 * Layered (Sugiyama-style) positions for the hierarchy view. Levels come from the backbone;
 * within each level, nodes are ordered by the BARYCENTER (mean position) of their parents so
 * the backbone has few crossings. Returns pixel positions for ECharts `layout: "none"`.
 */
function computeHierarchyLayout(
  nodes: Concept[],
  edges: ConceptEdge[],
  rowGap = 140,
  colGap = 190
): Map<string, Point> {
  const { ids, parents, level, liveParent } = buildBackbone(nodes, edges);

  const byLevel = new Map<number, string[]>();
  ids.forEach((id) => {
    const lv = level.get(id)!;
    const row = byLevel.get(lv);
    if (row) row.push(id);
    else byLevel.set(lv, [id]);
  });

  // Barycenter ordering: sweep top-down a couple of times, sorting each level by the average
  // index of its surviving parents. This straightens the backbone and minimises crossings.
  const order = new Map<string, number>();
  byLevel.forEach((group) => group.forEach((id, i) => order.set(id, i)));
  const maxLv = byLevel.size ? Math.max(...byLevel.keys()) : 0;
  for (let pass = 0; pass < 2; pass++) {
    for (let lv = 1; lv <= maxLv; lv++) {
      const group = byLevel.get(lv);
      if (!group) continue;
      const bary = (id: string) => {
        const ps = [...parents.get(id)!].filter((p) => liveParent(p, id));
        if (!ps.length) return order.get(id)!;
        return ps.reduce((s, p) => s + (order.get(p) ?? 0), 0) / ps.length;
      };
      group.sort((a, b) => bary(a) - bary(b));
      group.forEach((id, i) => order.set(id, i));
    }
  }

  const pos = new Map<string, Point>();
  for (const [lv, group] of byLevel) {
    const width = (group.length - 1) * colGap;
    group.forEach((id, i) => {
      pos.set(id, { x: i * colGap - width / 2, y: lv * rowGap });
    });
  }
  return pos;
}

/**
 * The focus subgraph for a selected node, shared by the layered views (hierarchy / sankey) so
 * they re-root on a selection exactly like the tree view does: the selected node, all of its
 * backbone DESCENDANTS (following parent->child) and all of its backbone ANCESTORS (following
 * child->parent), plus every backbone edge among them. Unlike the tree it keeps EVERY parent edge
 * (not just a single primary parent), so a multi-parent concept still shows all of its links - the
 * DAG-native equivalent of the tree's dashed reference copies. The returned `ancestors` set lets a
 * caller fade the ancestor "breadcrumb" spine above the focused subtree. With no selection the
 * whole graph is returned unchanged and `ancestors` is empty.
 */
function focusSubgraph(
  graph: GraphPayload,
  selectedId: string | null | undefined
): { graph: GraphPayload; ancestors: Set<string> } {
  if (!selectedId || !graph.nodes.some((n) => n.id === selectedId)) {
    return { graph, ancestors: new Set<string>() };
  }
  const { parents, liveParent } = buildBackbone(graph.nodes, graph.edges);

  // Surviving child adjacency, derived from the parent map so cycle-broken edges stay dropped.
  const childrenOf = new Map<string, string[]>();
  for (const [child, ps] of parents) {
    for (const p of ps) {
      if (liveParent(p, child)) (childrenOf.get(p) ?? childrenOf.set(p, []).get(p)!).push(child);
    }
  }

  const reach = (start: string, next: (id: string) => Iterable<string>): Set<string> => {
    const seen = new Set<string>();
    let frontier = [start];
    while (frontier.length) {
      const batch: string[] = [];
      for (const id of frontier) {
        for (const nb of next(id)) {
          if (nb !== start && !seen.has(nb)) {
            seen.add(nb);
            batch.push(nb);
          }
        }
      }
      frontier = batch;
    }
    return seen;
  };

  const descendants = reach(selectedId, (id) => childrenOf.get(id) ?? []);
  const ancestors = reach(selectedId, (id) => parents.get(id) ?? []);
  // A node reachable both ways (rare, via diamond paths) reads as part of the subtree, not spine.
  descendants.forEach((id) => ancestors.delete(id));

  const visible = new Set<string>([selectedId, ...descendants, ...ancestors]);
  return {
    graph: {
      nodes: graph.nodes.filter((n) => visible.has(n.id)),
      edges: graph.edges.filter((e) => visible.has(e.source.id) && visible.has(e.target.id)),
    },
    ancestors,
  };
}

/**
 * Per-node visual style shared by the tree and sankey views so a concept reads the same
 * everywhere: heat colour by structural reach, hollow dashed ring while still a frontier node,
 * dark ring when selected.
 */
function nodeStyle(n: Concept, selectedId: string | null | undefined, denom: number) {
  const frontier = n.times_expanded === 0;
  const selected = n.id === selectedId;
  const base = heatColor(Math.log2(nodeWeight(n) + 1) / denom);
  return {
    // Frontier nodes are hollow but tinted (not pure white) so they stay visible on the canvas.
    color: frontier ? frontierFill(base) : base,
    borderColor: selected ? "#0f172a" : base,
    borderWidth: selected ? 4 : frontier ? 2 : 1,
    borderType: frontier ? ("dashed" as const) : ("solid" as const),
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type EChartsOption = any;

/**
 * Sankey view: the directional backbone becomes top-to-bottom flow ribbons whose width is the
 * edge weight, coloured by relation. Isolated nodes are dropped because sankey cannot place a
 * node with no flow.
 */
function buildSankeyOption(
  graph: GraphPayload,
  nameById: Map<string, string>,
  selectedId: string | null | undefined,
  maxWeight: number,
  ancestors: Set<string>
): EChartsOption {
  const { level, liveParent } = buildBackbone(graph.nodes, graph.edges);
  const denom = Math.log2(maxWeight + 1) || 1;

  const links: EChartsOption[] = [];
  for (const e of graph.edges) {
    const dir = HIERARCHY_PARENT[e.relation];
    if (!dir) continue;
    const parent = dir === "source" ? e.source.id : e.target.id;
    const child = dir === "source" ? e.target.id : e.source.id;
    if (parent === child || !liveParent(parent, child)) continue;
    if (level.get(parent) === undefined || level.get(child) === undefined) continue;
    // Ribbons feeding the ancestor breadcrumb spine are faded so the focused subtree stands out.
    const faded = ancestors.has(parent) || ancestors.has(child);
    links.push({
      source: parent,
      target: child,
      value: Math.max(0.5, e.weight),
      lineStyle: { color: relationColor(e.relation), opacity: faded ? 0.12 : 0.4 },
    });
  }

  const linked = new Set<string>();
  links.forEach((l) => {
    linked.add(l.source);
    linked.add(l.target);
  });
  const data = graph.nodes
    .filter((n) => linked.has(n.id))
    .map((n) => {
      const style = nodeStyle(n, selectedId, denom);
      return {
        name: n.id,
        value: nodeWeight(n),
        _name: n.name,
        _desc: n.description,
        _negative: n.negative_description,
        _weight: nodeWeight(n),
        // Ancestor spine nodes are dimmed to match the tree view's faded breadcrumb.
        itemStyle: ancestors.has(n.id) ? { ...style, opacity: 0.5 } : style,
      };
    });

  return {
    tooltip: {
      confine: true,
      formatter: (p: { dataType?: string; data?: EChartsOption }) =>
        p.dataType === "edge"
          ? `${nameById.get(p.data?.source) ?? ""} &rarr; ${nameById.get(p.data?.target) ?? ""}`
          : nodeTooltipHtml({
              name: p.data?._name ?? "",
              weight: p.data?._weight,
              desc: p.data?._desc,
              negative: p.data?._negative,
            }),
    },
    series: [
      {
        type: "sankey",
        orient: "vertical",
        data,
        links,
        roam: true,
        draggable: false,
        nodeWidth: 14,
        nodeGap: 14,
        label: {
          position: "top",
          fontSize: 12,
          formatter: (p: { name?: string }) => nameById.get(p.name ?? "") ?? p.name ?? "",
        },
        lineStyle: { curveness: 0.5 },
        emphasis: { focus: "adjacency" },
      },
    ],
  };
}

/**
 * Tree view: each node is placed under a single primary parent (its deepest surviving backbone
 * parent) so the DAG collapses into a clean top-down tree. When a node is selected the tree is
 * RE-ROOTED on it - the selected node's full subtree fills the view and its ancestors are drawn
 * above it as a faded breadcrumb spine, so you keep context without the rest of the forest. With
 * no selection the whole forest is shown under a hidden virtual root.
 *
 * Edges are coloured by the relation joining a node to its primary parent (matching the other
 * views' relation key) and subtrees collapse/expand on click. The tree keeps a single parent per
 * node; a multi-parent concept's other parents are the hierarchy / sankey views' job.
 */
function buildTreeOption(
  graph: GraphPayload,
  selectedId: string | null | undefined,
  maxWeight: number
): EChartsOption {
  const { ids, parents, level, liveParent } = buildBackbone(graph.nodes, graph.edges);
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const denom = Math.log2(maxWeight + 1) || 1;

  // Relation on each surviving parent->child backbone edge, so each tree edge can be coloured by
  // the relation that produced it (the edge from a node to its parent carries the node's style).
  const relByPair = new Map<string, string>();
  for (const e of graph.edges) {
    const dir = HIERARCHY_PARENT[e.relation];
    if (!dir) continue;
    const parent = dir === "source" ? e.source.id : e.target.id;
    const child = dir === "source" ? e.target.id : e.source.id;
    if (parent === child) continue;
    const key = `${parent}>${child}`;
    if (!relByPair.has(key)) relByPair.set(key, e.relation);
  }

  // Primary parent = the surviving parent with the greatest level (deepest), so a node attaches
  // to its most specific ancestor; the rest become a forest under a hidden virtual root.
  const kids = new Map<string, string[]>(ids.map((id) => [id, []]));
  const primaryParentOf = new Map<string, string | null>();
  const roots: string[] = [];
  for (const c of ids) {
    let best: string | null = null;
    let bestLv = -1;
    for (const p of parents.get(c)!) {
      if (!liveParent(p, c)) continue;
      const lv = level.get(p)!;
      if (lv > bestLv) {
        bestLv = lv;
        best = p;
      }
    }
    primaryParentOf.set(c, best);
    if (best) kids.get(best)!.push(c);
    else roots.push(c);
  }

  // The tree keeps a single parent per node (a clean top-down tree). A node's OTHER backbone
  // parents are deliberately NOT shown - the hierarchy / sankey (DAG) views are where a
  // multi-parent concept like "philosophy of science" shows every parent link converging on it.
  const sizeOf = (conn: number) => Math.min(46, 14 + Math.log2(conn + 1) * 5);

  // Build a node and (recursively) its subtree of primary-parent children.
  const make = (id: string): EChartsOption => {
    const n = byId.get(id)!;
    const conn = nodeWeight(n);
    const selected = n.id === selectedId;
    const parent = primaryParentOf.get(id) ?? null;
    const rel = parent ? relByPair.get(`${parent}>${id}`) : undefined;
    return {
      name: id,
      value: conn,
      _name: n.name,
      _desc: n.description,
      _negative: n.negative_description,
      _weight: conn,
      symbolSize: sizeOf(conn) + (selected ? 10 : 0),
      label: { fontWeight: selected ? "bold" : "normal" },
      itemStyle: nodeStyle(n, selectedId, denom),
      lineStyle: rel ? { color: relationColor(rel) } : undefined,
      children: kids.get(id)!.map(make),
    };
  };

  // Focus mode: re-root on the selected node (its full subtree) and wrap its ancestors above it
  // as a single-child, faded breadcrumb spine so the path from a root stays visible. The spine
  // follows the primary-parent chain (one parent per node) - multi-parent context is the
  // hierarchy / sankey views' job, not the tree's.
  const focus = selectedId && byId.has(selectedId) ? selectedId : null;
  let rootData: EChartsOption;
  if (focus) {
    const chain: string[] = [];
    const guard = new Set<string>();
    let cur: string | null = focus;
    while (cur && !guard.has(cur)) {
      guard.add(cur);
      chain.unshift(cur);
      cur = primaryParentOf.get(cur) ?? null;
    }
    let node = make(focus);
    for (let i = chain.length - 2; i >= 0; i--) {
      const aId = chain[i];
      const a = byId.get(aId)!;
      const conn = nodeWeight(a);
      const parent = primaryParentOf.get(aId) ?? null;
      const rel = parent ? relByPair.get(`${parent}>${aId}`) : undefined;
      node = {
        name: aId,
        value: conn,
        _name: a.name,
        _desc: a.description,
        _negative: a.negative_description,
        _weight: conn,
        symbolSize: sizeOf(conn),
        itemStyle: { ...nodeStyle(a, selectedId, denom), opacity: 0.5 },
        lineStyle: rel ? { color: relationColor(rel), opacity: 0.5 } : { opacity: 0.5 },
        children: [node],
      };
    }
    rootData = node;
  } else {
    rootData =
      roots.length === 1
        ? make(roots[0])
        : {
            name: "__root__",
            symbolSize: 0,
            label: { show: false },
            lineStyle: { opacity: 0 },
            children: roots.map(make),
          };
  }

  return {
    tooltip: {
      confine: true,
      formatter: (p: { data?: EChartsOption }) => {
        const d = p.data;
        if (!d?._name) return "";
        return nodeTooltipHtml({
          name: d._name,
          weight: d._weight,
          desc: d._desc,
          negative: d._negative,
        });
      },
    },
    series: [
      {
        type: "tree",
        data: [rootData],
        orient: "TB",
        roam: true,
        // Start fully expanded (the neighborhood depth filter already bounds the tree's size),
        // but let the user collapse/expand any subtree by clicking its node.
        initialTreeDepth: -1,
        expandAndCollapse: true,
        edgeShape: "polyline",
        label: {
          position: "top",
          verticalAlign: "middle",
          align: "right",
          fontSize: 12,
          formatter: (p: { name?: string; data?: EChartsOption }) =>
            p.name === "__root__" ? "" : (p.data?._name ?? p.name ?? ""),
        },
        leaves: { label: { position: "bottom", align: "left" } },
        // Neutral fallback; per-node lineStyle above recolours each edge by its relation.
        lineStyle: { color: "#94a3b8", width: 1.5 },
        emphasis: { focus: "descendant" },
      },
    ],
  };
}

type LayoutMode = "force" | "hierarchy" | "tree" | "sankey";

// Persist the chosen layout across reloads so a refresh keeps the user's view.
const LAYOUT_MODE_KEY = "knowledge.layoutMode.v1";
const LAYOUT_MODES: LayoutMode[] = ["force", "hierarchy", "tree", "sankey"];

function loadLayoutMode(): LayoutMode {
  try {
    const raw = localStorage.getItem(LAYOUT_MODE_KEY);
    if (raw && LAYOUT_MODES.includes(raw as LayoutMode)) {
      return raw as LayoutMode;
    }
  } catch {
    // localStorage unavailable - fall through to the default.
  }
  return "tree";
}

/**
 * Restrict the graph to the nodes within `depth` hops of `centerId` (BFS over the UNDIRECTED
 * edge graph), plus every edge whose endpoints both survive. depth 1 -> the centre and its
 * direct neighbors; depth 2 -> also the neighbors of those neighbors; and so on. When there is
 * no centre (or it is not in the graph) the graph is returned unchanged.
 */
function neighborhood(
  graph: GraphPayload,
  centerId: string | null | undefined,
  depth: number
): GraphPayload {
  if (!centerId || depth < 1) return graph;
  const present = graph.nodes.some((n) => n.id === centerId);
  if (!present) return graph;

  // Undirected adjacency over the current edge set.
  const adj = new Map<string, Set<string>>();
  const link = (a: string, b: string) => {
    (adj.get(a) ?? adj.set(a, new Set()).get(a)!).add(b);
  };
  for (const e of graph.edges) {
    link(e.source.id, e.target.id);
    link(e.target.id, e.source.id);
  }

  // BFS outward, recording each node's hop distance so we stop at `depth`.
  const dist = new Map<string, number>([[centerId, 0]]);
  let frontier = [centerId];
  for (let d = 0; d < depth; d++) {
    const next: string[] = [];
    for (const id of frontier) {
      for (const nb of adj.get(id) ?? []) {
        if (!dist.has(nb)) {
          dist.set(nb, d + 1);
          next.push(nb);
        }
      }
    }
    frontier = next;
  }

  const visible = new Set(dist.keys());
  return {
    nodes: graph.nodes.filter((n) => visible.has(n.id)),
    edges: graph.edges.filter((e) => visible.has(e.source.id) && visible.has(e.target.id)),
  };
}

interface ConceptGraphProps {
  graph: GraphPayload;
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  /**
   * How many hops out from the selected node to render. depth 1 shows only the selected
   * node's neighbors; depth 2 also shows the neighbors of those neighbors; and so on. When
   * omitted (or no node is selected) the whole supplied graph is shown.
   */
  depth?: number;
  /** Double-clicking a node requests a single-level expansion of it. */
  onExpand?: (id: string) => void;
  /**
   * Identity of the current layout (e.g. the root/topic id). Changing it remounts the
   * chart for a fresh layout; keeping it stable lets updates merge in place so existing
   * nodes do not jump when new nodes arrive.
   */
  layoutKey?: string;
  className?: string;
}

// Node colour encodes a concept's recursive structural reach (subfields + everything it is a
// prerequisite for) on a continuous rainbow (jet) ramp: the lowest-reach concepts are blue,
// climbing through cyan/green/yellow to red for the concept that anchors the most structure in
// the current graph. Frontier (not-yet-expanded) nodes stay hollow.
const RAINBOW: [number, number, number][] = [
  [37, 99, 235], // blue   (#2563eb) - lowest reach
  [6, 182, 212], // cyan   (#06b6d4)
  [22, 163, 74], // green  (#16a34a)
  [234, 179, 8], // yellow (#eab308)
  [249, 115, 22], // orange (#f97316)
  [220, 38, 38], // red    (#dc2626) - highest reach
];

/** Multi-stop rainbow interpolation for a normalised position `t` in [0, 1]. */
function heatColor(t: number): string {
  const clamped = Math.max(0, Math.min(1, t));
  const span = clamped * (RAINBOW.length - 1);
  const i = Math.min(RAINBOW.length - 2, Math.floor(span));
  const f = span - i;
  const ch = (k: number) => Math.round(RAINBOW[i][k] + (RAINBOW[i + 1][k] - RAINBOW[i][k]) * f);
  return `rgb(${ch(0)}, ${ch(1)}, ${ch(2)})`;
}

/**
 * Hollow-but-visible fill for an un-expanded (frontier) node. A pure-white fill is invisible
 * against the white canvas, so blend the node's heat colour most of the way toward white: the
 * node still reads as "hollow / not yet expanded" (a pale tint with a dashed heat-coloured ring,
 * clearly lighter than a solid expanded node) yet stays visible on the background.
 */
function frontierFill(base: string): string {
  const m = base.match(/\d+/g);
  if (!m || m.length < 3) return "#eef2f7";
  const tint = (c: number) => Math.round(Number(c) + (255 - Number(c)) * 0.8);
  return `rgb(${tint(+m[0])}, ${tint(+m[1])}, ${tint(+m[2])})`;
}

/**
 * The value a node's colour and size encode: its recursive structural reach (subfields +
 * everything it is a prerequisite for, transitively), supplied by the backend. This captures how
 * much of the knowledge structure a concept anchors - the point of the graph - rather than its
 * raw neighbour count. Falls back to `connections` when `reach` is absent (e.g. test fixtures).
 */
function nodeWeight(n: Concept): number {
  return n.reach ?? n.connections ?? 0;
}

/**
 * Force-directed concept graph rendered with ECharts (`graph` series). Expanded nodes are
 * drawn solid; still-unexpanded "frontier" nodes are drawn hollow with a dashed ring so it is
 * obvious which nodes can still grow the graph. Pan/zoom (roam) and node drag are enabled.
 * Click selects a node; double-click requests a single-level expansion.
 */
export function ConceptGraph({
  graph: fullGraph,
  selectedId,
  onSelect,
  depth,
  onExpand,
  layoutKey,
  className,
}: ConceptGraphProps) {
  // The rendered graph is the selected node's `depth`-hop neighborhood (computed client-side
  // so it is instant and exact regardless of how much the backend returned). Everything below
  // - layouts, legends, click handling - operates on this filtered view.
  const graph = useMemo(
    () => (depth ? neighborhood(fullGraph, selectedId, depth) : fullGraph),
    [fullGraph, selectedId, depth]
  );
  // Settled pixel positions per node id, captured after the force layout finishes. Nodes we
  // have a position for are pinned (fixed) so they do not drift when new nodes arrive - only
  // brand-new nodes get force-placed. This keeps the graph still across refetches/expands.
  const posRef = useRef<Map<string, [number, number]>>(new Map());
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const instRef = useRef<any>(null);
  const nodes = graph.nodes;
  const [mode, setMode] = useState<LayoutMode>(loadLayoutMode);

  // Remember the chosen layout so a page refresh restores the same view.
  useEffect(() => {
    try {
      localStorage.setItem(LAYOUT_MODE_KEY, mode);
    } catch {
      // localStorage unavailable - persistence is best-effort.
    }
  }, [mode]);

  // The layered views (hierarchy / sankey) re-root on the selected node like the tree does:
  // filter to that node's lineage (subtree + ancestor spine). With no selection this is the full
  // graph. `focusAncestors` marks the spine nodes so they can be drawn faded.
  const { graph: layeredGraph, ancestors: focusAncestors } = useMemo(
    () =>
      mode === "hierarchy" || mode === "sankey"
        ? focusSubgraph(graph, selectedId)
        : { graph, ancestors: new Set<string>() },
    [graph, selectedId, mode]
  );

  // Layered positions for hierarchy mode (recomputed only when the focused graph or mode changes).
  const hierPos = useMemo(
    () =>
      mode === "hierarchy"
        ? computeHierarchyLayout(layeredGraph.nodes, layeredGraph.edges)
        : new Map<string, Point>(),
    [layeredGraph, mode]
  );

  const capturePositions = useCallback(() => {
    // Only the force layout needs pinning; hierarchy positions are computed deterministically.
    if (mode !== "force") return;
    const inst = instRef.current;
    if (!inst) return;
    try {
      const data = inst.getModel().getSeriesByIndex(0).getData();
      nodes.forEach((n, i) => {
        const layout = data.getItemLayout(i);
        if (layout && Number.isFinite(layout[0]) && Number.isFinite(layout[1])) {
          posRef.current.set(n.id, [layout[0], layout[1]]);
        }
      });
    } catch {
      // Internal layout API unavailable - degrade to merge-only (still no full re-layout).
    }
  }, [nodes, mode]);

  // Highest structural reach in the current graph anchors the red end of the ramp (log-scaled so
  // a single mega-hub does not flatten everyone else to blue).
  const maxWeight = useMemo(
    () => graph.nodes.reduce((m, n) => Math.max(m, nodeWeight(n)), 0),
    [graph.nodes]
  );

  // Relation types actually present in the current graph, in the canonical legend order.
  const presentRelations = useMemo(() => {
    const seen = new Set(graph.edges.map((e) => e.relation));
    return (Object.keys(RELATION_COLORS) as Relation[]).filter((r) => seen.has(r));
  }, [graph.edges]);

  // Lookups shared by the tree/sankey views (which key on node id) and the click handler.
  const nameById = useMemo(
    () => new Map(graph.nodes.map((n) => [n.id, n.name])),
    [graph.nodes]
  );
  const nodeIdSet = useMemo(() => new Set(graph.nodes.map((n) => n.id)), [graph.nodes]);

  const option = useMemo(() => {
    // Tree and sankey are their own ECharts series types with a wholly different option shape.
    // Sankey re-roots on the selection (layeredGraph) and fades the ancestor spine, like the tree.
    if (mode === "sankey")
      return buildSankeyOption(layeredGraph, nameById, selectedId, maxWeight, focusAncestors);
    if (mode === "tree") return buildTreeOption(graph, selectedId, maxWeight);

    const hierarchical = mode === "hierarchy";
    const pinned = posRef.current;
    const denom = Math.log2(maxWeight + 1) || 1;

    // Hierarchy mode operates on the selection-focused lineage (layeredGraph) so it re-roots like
    // the tree; force mode uses the whole graph.
    const g = hierarchical ? layeredGraph : graph;

    // Every edge is a directional backbone edge. Hierarchy mode shows only the nodes that take
    // part in that backbone, so a concept with no backbone link is not left floating; force mode
    // shows every node.
    const edges = g.edges;
    const backboneNodeIds = hierarchical
      ? new Set(edges.flatMap((e) => [e.source.id, e.target.id]))
      : null;
    const visibleNodes = backboneNodeIds
      ? g.nodes.filter((n) => backboneNodeIds.has(n.id))
      : g.nodes;

    const data = visibleNodes.map((n) => {
      const frontier = n.times_expanded === 0;
      const selected = n.id === selectedId;
      // In hierarchy focus mode the ancestors above the selection are a faded breadcrumb spine.
      const ancestor = hierarchical && focusAncestors.has(n.id);
      const weight = nodeWeight(n);
      const base = heatColor(Math.log2(weight + 1) / denom);
      // Hierarchy mode uses deterministic layered positions; force mode uses pinned ones.
      const hp = hierarchical ? hierPos.get(n.id) : undefined;
      const pos = hierarchical
        ? hp
          ? ([hp.x, hp.y] as [number, number])
          : undefined
        : pinned.get(n.id);
      // Node size also scales with reach so structurally larger concepts read bigger, with a
      // floor so leaf/frontier nodes stay clickable. The selected node is bumped up further.
      const size = Math.min(56, 22 + Math.log2(weight + 1) * 7);
      return {
        id: n.id,
        name: n.name,
        symbolSize: selected ? size + 12 : size,
        _frontier: frontier,
        _desc: n.description,
        _negative: n.negative_description,
        _weight: weight,
        // Pin already-placed nodes so the layout stays put; new nodes (no stored position)
        // are placed by the force layout among the pinned ones.
        ...(pos ? { x: pos[0], y: pos[1], fixed: true } : {}),
        label: { fontWeight: selected ? "bold" : "normal", opacity: ancestor ? 0.55 : 1 },
        itemStyle: {
          // Frontier nodes stay hollow but tinted (not pure white, which would be invisible on
          // the canvas) and keep the heat colour on their dashed border.
          color: frontier ? frontierFill(base) : base,
          borderColor: selected ? "#0f172a" : base,
          borderWidth: selected ? 4 : frontier ? 2 : 1,
          borderType: frontier ? "dashed" : "solid",
          // Ancestor spine nodes are dimmed to match the tree view's faded breadcrumb.
          ...(ancestor ? { opacity: 0.5 } : {}),
        },
      };
    });

    const links = edges.map((e) => {
      // Hierarchy mode keeps edges nearly straight to show the layering; force mode uses a
      // uniform gentle curve.
      const curveness = hierarchical ? 0.05 : 0.12;
      // Edges feeding the ancestor spine are faded so the focused subtree stands out.
      const faded =
        hierarchical && (focusAncestors.has(e.source.id) || focusAncestors.has(e.target.id));
      return {
        source: e.source.id,
        target: e.target.id,
        value: e.relation,
        symbol: ["none", "arrow"],
        symbolSize: 7,
        lineStyle: {
          width: 1 + e.weight * 3,
          curveness,
          color: relationColor(e.relation),
          opacity: faded ? 0.2 : 0.7,
        },
      };
    });

    return {
      tooltip: {
        confine: true,
        formatter: (p: {
          dataType?: string;
          data?: {
            name?: string;
            _desc?: string;
            _negative?: string;
            _weight?: number;
            value?: string;
          };
        }) =>
          p.dataType === "node"
            ? nodeTooltipHtml({
                name: p.data?.name ?? "",
                weight: p.data?._weight,
                desc: p.data?._desc,
                negative: p.data?._negative,
              })
            : String(p.data?.value ?? ""),
      },
      series: [
        {
          type: "graph",
          // Hierarchy mode places nodes itself (layout "none"); force mode runs the simulation.
          layout: hierarchical ? "none" : "force",
          roam: true,
          draggable: true,
          data,
          links,
          force: { repulsion: 260, edgeLength: 130, gravity: 0.06, friction: 0.2 },
          label: { show: true, position: "right", fontSize: 12 },
          edgeSymbol: ["none", "arrow"],
          edgeSymbolSize: 7,
          // Per-link colour set above (by relation type); keep edges semi-transparent.
          lineStyle: { opacity: 0.7 },
          emphasis: {
            focus: "adjacency",
            label: { show: true },
            edgeLabel: { show: true, formatter: (p: { value?: string }) => p.value ?? "" },
          },
        },
      ],
    };
  }, [
    graph,
    layeredGraph,
    focusAncestors,
    selectedId,
    maxWeight,
    mode,
    hierPos,
    nameById,
  ]);

  const onEvents = useMemo(() => {
    // Across series types the clicked node id lives in different fields: graph nodes carry
    // `data.id`; tree/sankey nodes carry `data.name` (= the node id). Pick whichever resolves
    // to a real node so a click selects it (and the virtual tree root is ignored).
    const nodeId = (p: { data?: { id?: string; name?: string } }) => {
      const id = p.data?.id ?? p.data?.name;
      return id && nodeIdSet.has(id) ? id : null;
    };
    return {
      click: (p: { data?: { id?: string; name?: string } }) => {
        const id = nodeId(p);
        if (id) onSelect?.(id);
      },
      dblclick: (p: { data?: { id?: string; name?: string } }) => {
        const id = nodeId(p);
        if (id) onExpand?.(id);
      },
      // After each layout settles, remember where nodes ended up so the next update pins them.
      finished: capturePositions,
    };
  }, [onSelect, onExpand, capturePositions, nodeIdSet]);

  if (graph.nodes.length === 0) {
    return (
      <div
        data-testid="concept-graph-empty"
        className="flex h-full w-full items-center justify-center text-sm text-muted-foreground"
      >
        No graph yet. Create a node and start expansion.
      </div>
    );
  }

  return (
    <div
      data-testid="concept-graph"
      className={className}
      style={{ position: "relative", height: "100%", width: "100%" }}
    >
      <LayoutToggle mode={mode} onChange={setMode} />
      <ReactECharts
        // Remount when the topic/root OR the layout mode changes (fresh layout); within a
        // topic+mode, updates MERGE so existing nodes keep their settled positions and the
        // graph does not jump around on every refetch/expand. lazyUpdate avoids re-renders.
        key={`${layoutKey ?? "kg"}-${mode}`}
        option={option}
        onEvents={onEvents}
        onChartReady={(inst) => {
          instRef.current = inst;
        }}
        notMerge={false}
        lazyUpdate
        style={{ height: "100%", width: "100%" }}
      />
      <ReachLegend maxWeight={maxWeight} />
      <RelationsLegend relations={presentRelations} />
    </div>
  );
}

/** Top-centre switch between the force, layered hierarchy, tree, and sankey layouts. */
function LayoutToggle({
  mode,
  onChange,
}: {
  mode: LayoutMode;
  onChange: (m: LayoutMode) => void;
}) {
  const options: { value: LayoutMode; label: string }[] = [
    { value: "force", label: "Force" },
    { value: "hierarchy", label: "Hierarchy" },
    { value: "tree", label: "Tree" },
    { value: "sankey", label: "Sankey" },
  ];
  return (
    <div
      data-testid="concept-graph-layout-toggle"
      className="absolute left-1/2 top-3 z-10 inline-flex -translate-x-1/2 overflow-hidden rounded-md border bg-card/90 text-[11px] shadow-sm backdrop-blur"
    >
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={mode === o.value}
          onClick={() => onChange(o.value)}
          className={
            mode === o.value
              ? "bg-primary px-2.5 py-1 font-medium text-primary-foreground"
              : "px-2.5 py-1 text-muted-foreground hover:bg-muted"
          }
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** The legend lists the relation types that actually appear in the current graph. */
function RelationsLegend({ relations }: { relations: Relation[] }) {
  const shown = relations;
  if (shown.length === 0) return null;
  return (
    <div
      data-testid="concept-graph-relations-legend"
      className="pointer-events-none absolute bottom-3 right-3 rounded-md border bg-card/90 px-2 py-1.5 text-[10px] shadow-sm backdrop-blur"
    >
      <div className="mb-1 font-medium text-muted-foreground">Relations</div>
      <ul className="space-y-0.5">
        {shown.map((r) => (
          <li key={r} className="flex items-center gap-1.5">
            <span
              className="inline-block h-0.5 w-4 rounded-full"
              style={{ backgroundColor: RELATION_COLORS[r] }}
            />
            <span className="text-muted-foreground">{RELATION_LABELS[r]}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A small blue -> red colour bar in the corner explaining the node-colour encoding. */
function ReachLegend({ maxWeight }: { maxWeight: number }) {
  const gradient = `linear-gradient(to right, ${RAINBOW.map((_, i) =>
    heatColor(i / (RAINBOW.length - 1))
  ).join(", ")})`;
  return (
    <div
      data-testid="concept-graph-legend"
      className="pointer-events-none absolute bottom-3 left-3 rounded-md border bg-card/90 px-2 py-1.5 text-[10px] shadow-sm backdrop-blur"
    >
      <div
        className="mb-1 font-medium text-muted-foreground"
        title="Recursive subfields + everything this concept is a prerequisite for"
      >
        Reach
      </div>
      <div className="h-2 w-32 rounded-full" style={{ background: gradient }} />
      <div className="mt-0.5 flex justify-between tabular-nums text-muted-foreground">
        <span>0</span>
        <span>{maxWeight}</span>
      </div>
    </div>
  );
}
