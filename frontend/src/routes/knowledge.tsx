import { type ReactNode, useCallback, useMemo, useRef, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { AppShell } from "@/components/layout/AppShell";
import { FullBleed } from "@/components/layout/FullBleed";
import { ConceptGraph } from "@/components/knowledge/ConceptGraph";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

/** A floating, minimisable panel laid over the graph. */
function OverlayCard({
  title,
  children,
  className,
  defaultOpen = true,
}: {
  title: string;
  children: ReactNode;
  className?: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div
      className={cn(
        "absolute z-10 w-72 rounded-lg border bg-card/95 shadow-lg backdrop-blur",
        className
      )}
    >
      <div className="flex items-center justify-between border-b px-3 py-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-label={open ? `Minimise ${title}` : `Expand ${title}`}
          className="flex size-5 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          {open ? "–" : "+"}
        </button>
      </div>
      {open && <div className="max-h-[72vh] space-y-3 overflow-auto p-3">{children}</div>}
    </div>
  );
}
import {
  useAutoExpand,
  useClearExpansionQueue,
  useConcept,
  useConceptGraph,
  useConcepts,
  useCreateConcept,
  useDeleteConcept,
  useReduceTransitiveEdges,
  useRerankAll,
  useStartExpansion,
} from "@/hooks/useKnowledge";
import { createNodeSchema, type CreateNodeForm } from "@/schemas/knowledge";

export const Route = createFileRoute("/knowledge")({
  component: KnowledgePage,
});

function KnowledgePage() {
  // The node whose subgraph fills the canvas. The graph is topic-agnostic - any concept can
  // be a viewing root; picking one just centres the BFS subgraph on it.
  const [rootId, setRootId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [hops, setHops] = useState(2);
  const [live, setLive] = useState(false);
  // Nodes we have already fired an expansion for this session (avoid re-requesting
  // while the async expansion is still in flight and the graph has not refetched yet).
  const requestedRef = useRef<Set<string>>(new Set());

  // Concepts ranked by structural reach (recursive subfields + prerequisite-for) - the same
  // metric the graph colours by and that auto-expand seeds its hubs from. Reach is computed
  // server-side across the WHOLE graph, so this ordering is global (not just within the returned
  // page). Drives the concept table, the auto-expand hub preview, and the default viewing root.
  const TOP_CONCEPTS = 5;
  const rankedConcepts = useConcepts(
    search ? { search, ordering: "-reach" } : { ordering: "-reach" },
    live
  );

  // Until the user picks a viewing root, fall back to the highest-reach concept (only when not
  // searching, so the canvas does not jump around as the list filters).
  const effectiveRootId = useMemo(
    () => rootId ?? (search ? null : (rankedConcepts.data?.results[0]?.id ?? null)),
    [rootId, search, rankedConcepts.data]
  );

  // The selected node defaults to the viewing root until the user picks another node.
  const effectiveSelectedId = selectedId ?? effectiveRootId;

  // Clicking a node in the graph re-roots the view on it: the canvas re-centres the BFS
  // subgraph on the clicked node so its connections fill the view, and it becomes selected.
  function focusNode(id: string) {
    setRootId(id);
    setSelectedId(id);
  }

  const graph = useConceptGraph(effectiveRootId, hops, live);
  const detail = useConcept(effectiveSelectedId, live);

  const createConcept = useCreateConcept();
  const startExpansion = useStartExpansion();
  const deleteConcept = useDeleteConcept();
  const rerankAll = useRerankAll();
  const reduceEdges = useReduceTransitiveEdges();
  const clearQueue = useClearExpansionQueue();
  const autoExpandMut = useAutoExpand();

  // Auto-expand: crawl the top 5 highest-reach concepts outward, expanding their frontier
  // ring by ring (depth 1, then 2, then 3). The backend picks the hubs and runs the crawl; we
  // just kick it off and turn on live polling to watch the graph grow.
  const AUTO_EXPAND_MAX_DEPTH = 3;
  function runAutoExpand() {
    autoExpandMut.mutate(AUTO_EXPAND_MAX_DEPTH, { onSuccess: () => setLive(true) });
  }

  // Hard stop for a runaway crawl: forget what we have already requested this session, and
  // purge + cancel the backend queue so queued/in-flight tasks self-drop.
  function clearExpansionQueue() {
    requestedRef.current.clear();
    clearQueue.mutate();
  }

  // Graph-wide rerank-and-prune: queue the LLM clean-up (keep each hub's most important ~15 edges,
  // drop the rest) for every node over the trigger across the whole graph. Runs async server-side,
  // so turn on live polling to watch the pruned graph settle.
  function rerankAllHubs() {
    rerankAll.mutate(undefined, { onSuccess: () => setLive(true) });
  }

  // Delete a node (and its edges, server-side cascade). If it was the viewing root or the
  // selected node, drop those so the canvas falls back to another concept instead of
  // pointing at a node that no longer exists.
  function removeNode(id: string, name: string) {
    if (!window.confirm(`Delete "${name}" and all its connections? This cannot be undone.`)) {
      return;
    }
    deleteConcept.mutate(id, {
      onSuccess: () => {
        requestedRef.current.delete(id);
        if (rootId === id) setRootId(null);
        if (selectedId === id) setSelectedId(null);
      },
    });
  }

  const form = useForm<CreateNodeForm>({
    resolver: zodResolver(createNodeSchema),
    defaultValues: { name: "", negative_description: "" },
  });

  function onCreate(values: CreateNodeForm) {
    const negative = values.negative_description?.trim();
    createConcept.mutate(
      { name: values.name, ...(negative ? { negative_description: negative } : {}) },
      {
        onSuccess: (concept) => {
          setRootId(concept.id);
          setSelectedId(concept.id);
          form.reset();
        },
      }
    );
  }

  // Expand the selected node out to `degree` hops. 1st degree expands just the node (its
  // neighbors land as un-expanded frontier); 2nd degree then expands those neighbors; 3rd
  // goes one ring further; and so on. We force so the degree buttons re-expand even a node
  // that was already expanded (force only applies to the root - the recursion expands the
  // un-expanded frontier nodes normally).
  function expandNode(id: string, degree: number) {
    requestedRef.current.add(id);
    startExpansion.mutate(
      { id, body: { max_depth: degree, force: true } },
      { onSuccess: () => setLive(true) }
    );
  }

  // Does "expand to <degree>" still have anything to do? It expands the selected node's ball of
  // radius (degree - 1) hops; if every node in that ball is already expanded there is nothing
  // left to grow, so we fade the button out (it would only fire a no-op crawl). When the loaded
  // subgraph is too shallow to see that far, we cannot be sure, so we leave the button enabled.
  const degreeHasWork = useCallback(
    (degree: number): boolean => {
      const center = effectiveSelectedId;
      if (!center || !graph.data) return true;
      const radius = degree - 1;
      if (radius > hops) return true; // can't see far enough to be certain
      const expandedOf = new Map(graph.data.nodes.map((n) => [n.id, n.times_expanded]));
      if (!expandedOf.has(center)) return true; // selected node not in the loaded subgraph
      const adj = new Map<string, string[]>();
      const link = (a: string, b: string) => {
        (adj.get(a) ?? adj.set(a, []).get(a)!).push(b);
      };
      for (const e of graph.data.edges) {
        link(e.source.id, e.target.id);
        link(e.target.id, e.source.id);
      }
      // BFS the ball of radius `radius`; any still-unexpanded node in it means there is work.
      const dist = new Map<string, number>([[center, 0]]);
      const queue = [center];
      for (let i = 0; i < queue.length; i++) {
        const id = queue[i];
        const d = dist.get(id)!;
        if ((expandedOf.get(id) ?? 0) === 0) return true;
        if (d === radius) continue;
        for (const nb of adj.get(id) ?? []) {
          if (!dist.has(nb)) {
            dist.set(nb, d + 1);
            queue.push(nb);
          }
        }
      }
      return false;
    },
    [effectiveSelectedId, graph.data, hops]
  );

  return (
    <AppShell>
      {/* Full-bleed: break out of AppShell's main padding so the graph fills the content
          column between the sticky header (h-14) and the status bar (h-9). */}
      <FullBleed>
        {/* Graph fills the whole area as the main canvas */}
        <div className="absolute inset-0">
          {graph.data ? (
            <ConceptGraph
              graph={graph.data}
              selectedId={effectiveSelectedId}
              depth={hops}
              onSelect={focusNode}
              onExpand={(id) => expandNode(id, 1)}
              layoutKey={effectiveRootId ?? undefined}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              {effectiveRootId
                ? "Loading graph..."
                : "Create or select a concept to view its graph."}
            </div>
          )}
        </div>

        {/* Left overlay: build + concepts + view controls */}
        <OverlayCard title="Build" className="left-3 top-3">
          <form onSubmit={form.handleSubmit(onCreate)} className="space-y-2">
            <div className="space-y-1">
              <Label htmlFor="kg-name">New concept</Label>
              <Input id="kg-name" placeholder="physics" {...form.register("name")} />
              {form.formState.errors.name && (
                <p className="text-xs text-destructive">
                  {form.formState.errors.name.message}
                </p>
              )}
            </div>
            <div className="space-y-1">
              <Label htmlFor="kg-negative">Not to be confused with (optional)</Label>
              <Input
                id="kg-negative"
                placeholder="e.g. not the philosophical sense"
                {...form.register("negative_description")}
              />
              {form.formState.errors.negative_description && (
                <p className="text-xs text-destructive">
                  {form.formState.errors.negative_description.message}
                </p>
              )}
            </div>
            <Button type="submit" className="w-full" size="sm" disabled={createConcept.isPending}>
              {createConcept.isPending ? "Creating..." : "Create concept"}
            </Button>
          </form>

          <div className="border-t pt-3">
            <div className="mb-2 flex items-center gap-2">
              <Label htmlFor="kg-hops" className="text-xs">
                View depth
              </Label>
              <input
                id="kg-hops"
                type="range"
                min={1}
                max={4}
                value={hops}
                onChange={(e) => setHops(Number(e.target.value))}
                className="flex-1"
              />
              <span className="text-xs tabular-nums">{hops}</span>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" size="sm" onClick={() => graph.refetch()}>
                Refresh
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={reduceEdges.isPending}
                onClick={() => reduceEdges.mutate()}
                title="Remove edges implied by a longer path (transitive reduction of the hierarchy): drops A->C when A->B->C exists"
              >
                {reduceEdges.isPending ? "Reducing..." : "Reduce edges"}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={rerankAll.isPending}
                onClick={rerankAllHubs}
                title="Ask the LLM to rerank-and-prune EVERY hub over the trigger across the whole graph"
              >
                {rerankAll.isPending ? "Reranking..." : "Rerank & prune edges"}
              </Button>
            </div>
            {reduceEdges.isSuccess && (
              <p className="mt-2 text-xs text-emerald-600">
                Removed {reduceEdges.data.removed} redundant edge
                {reduceEdges.data.removed === 1 ? "" : "s"}.
              </p>
            )}
            {rerankAll.isSuccess && (
              <p className="mt-2 text-xs text-emerald-600">
                Rerank queued for {rerankAll.data.queued} hub
                {rerankAll.data.queued === 1 ? "" : "s"} - the graph will prune as they land.
              </p>
            )}
          </div>

          <div className="border-t pt-3">
            <h3 className="mb-2 text-xs font-semibold text-muted-foreground">
              Concepts (highest reach first)
            </h3>
            <Input
              placeholder="Search concepts..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="mb-2 h-8 text-xs"
            />
            {rankedConcepts.isLoading && (
              <p className="text-xs text-muted-foreground">Loading...</p>
            )}
            {rankedConcepts.data?.results.length === 0 && (
              <p className="text-xs text-muted-foreground">No concepts yet.</p>
            )}
            <ul className="space-y-1">
              {rankedConcepts.data?.results.slice(0, TOP_CONCEPTS).map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setRootId(c.id);
                      setSelectedId(c.id);
                    }}
                    className={`flex w-full items-center justify-between rounded px-2 py-1 text-left text-sm transition-colors hover:bg-muted ${
                      effectiveRootId === c.id ? "bg-muted font-medium" : ""
                    }`}
                  >
                    <span className="truncate">{c.name}</span>
                    <span className="ml-2 flex shrink-0 items-center gap-1.5">
                      {c.times_expanded === 0 && (
                        <span className="text-xs text-muted-foreground">new</span>
                      )}
                      <span
                        className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-muted-foreground"
                        title={`reach ${c.reach ?? 0} (${c.connections} connections)`}
                      >
                        {c.reach ?? 0}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </OverlayCard>

        {/* Bottom-left overlay: auto-expand order (the top-5 highest-reach hubs to be crawled) */}
        <OverlayCard title="Auto-expand (top 5 hubs)" className="bottom-3 left-3">
          <p className="text-xs text-muted-foreground">
            Auto-expand crawls these top 5 highest-reach concepts, growing each one's frontier
            outward ring by ring (depth 1, then 2, then 3).
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="default"
              size="sm"
              className="flex-1"
              disabled={autoExpandMut.isPending || !rankedConcepts.data?.results.length}
              onClick={runAutoExpand}
              title="Crawl the top 5 highest-reach concepts outward to depth 3"
            >
              {autoExpandMut.isPending ? "Auto-expanding..." : "Auto-expand top 5"}
            </Button>
            <Button
              type="button"
              variant={live ? "default" : "outline"}
              size="sm"
              onClick={() => setLive((v) => !v)}
              title="Poll for new nodes/edges as expansions land"
            >
              {live ? "Live: on" : "Live: off"}
            </Button>
          </div>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            className="w-full"
            disabled={clearQueue.isPending}
            onClick={clearExpansionQueue}
            title="Stop the crawl now: purge the queue and cancel queued/in-flight expansions"
          >
            {clearQueue.isPending ? "Clearing..." : "Clear queue (stop)"}
          </Button>
          {clearQueue.isSuccess && (
            <p className="text-xs text-emerald-600">
              Queue cleared - purged {clearQueue.data.purged} queued task
              {clearQueue.data.purged === 1 ? "" : "s"}.
            </p>
          )}
          {autoExpandMut.isSuccess && (
            <p className="text-xs text-emerald-600">
              Crawling {autoExpandMut.data.hubs.length} hub
              {autoExpandMut.data.hubs.length === 1 ? "" : "s"} to depth{" "}
              {autoExpandMut.data.max_depth}.
            </p>
          )}
          {rankedConcepts.isLoading && (
            <p className="text-xs text-muted-foreground">Loading...</p>
          )}
          {rankedConcepts.data?.results.length === 0 && (
            <p className="text-xs text-muted-foreground">No concepts to expand yet.</p>
          )}
          <ol className="space-y-1">
            {rankedConcepts.data?.results.slice(0, TOP_CONCEPTS).map((c, i) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => focusNode(c.id)}
                  className={`flex w-full items-center gap-2 rounded px-2 py-1 text-left text-sm transition-colors hover:bg-muted ${
                    effectiveRootId === c.id ? "bg-muted font-medium" : ""
                  }`}
                >
                  <span className="w-4 shrink-0 text-[10px] tabular-nums text-muted-foreground">
                    {i + 1}.
                  </span>
                  <span className="truncate">{c.name}</span>
                  <span
                    className="ml-auto shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-muted-foreground"
                    title={`reach ${c.reach ?? 0} (${c.connections} connections)`}
                  >
                    {c.reach ?? 0}
                  </span>
                </button>
              </li>
            ))}
          </ol>
        </OverlayCard>

        {/* Right overlay: selected concept + expansion */}
        <OverlayCard title="Concept" className="right-3 top-3">
          {detail.data ? (
            <div className="space-y-2">
              <p className="font-medium">
                {detail.data.name}
                <span
                  className={`ml-2 rounded px-1.5 py-0.5 text-[10px] font-medium ${
                    detail.data.times_expanded === 0
                      ? "bg-amber-100 text-amber-700"
                      : "bg-muted text-muted-foreground"
                  }`}
                >
                  {detail.data.times_expanded === 0 ? "not expanded" : "expanded"}
                </span>
              </p>
              <p className="text-xs text-muted-foreground">
                expanded {detail.data.times_expanded}x
              </p>
              {detail.data.description && <p className="text-sm">{detail.data.description}</p>}
              {detail.data.negative_description && (
                <p className="text-xs italic text-muted-foreground">
                  Not to be confused with: {detail.data.negative_description}
                </p>
              )}

              <div className="space-y-2 border-t pt-2">
                <div>
                  <p className="mb-1 text-xs font-semibold text-muted-foreground">
                    Expand to degree
                  </p>
                  <div className="flex gap-2">
                    {([1, 2, 3] as const).map((degree) => {
                      // Fade out a degree once its whole ball (the node and everything within
                      // degree-1 hops) is already expanded - there is nothing left for it to do.
                      const hasWork = degreeHasWork(degree);
                      return (
                        <Button
                          key={degree}
                          type="button"
                          size="sm"
                          variant="outline"
                          className="flex-1"
                          disabled={
                            !effectiveSelectedId || startExpansion.isPending || !hasWork
                          }
                          onClick={() =>
                            effectiveSelectedId && expandNode(effectiveSelectedId, degree)
                          }
                          title={
                            !hasWork
                              ? "Already expanded to this degree - nothing left to expand"
                              : degree === 1
                                ? "Expand the selected node (its neighbors)"
                                : `Expand the selected node's frontier outward ${degree - 1} ` +
                                  `ring${degree - 1 === 1 ? "" : "s"} (its neighbors and beyond)`
                          }
                        >
                          {degree === 1 ? "1st" : degree === 2 ? "2nd" : "3rd"} degree
                        </Button>
                      );
                    })}
                  </div>
                </div>
                <Button
                  type="button"
                  variant="destructive"
                  size="sm"
                  className="w-full"
                  disabled={!effectiveSelectedId || deleteConcept.isPending}
                  onClick={() =>
                    detail.data && removeNode(detail.data.id, detail.data.name)
                  }
                >
                  {deleteConcept.isPending ? "Deleting..." : "Delete"}
                </Button>
              </div>
              {startExpansion.isSuccess && (
                <p className="text-xs text-emerald-600">Expansion started.</p>
              )}

              <div className="border-t pt-2">
                <p className="text-xs font-semibold text-muted-foreground">
                  Neighbors ({detail.data.outgoing.length})
                </p>
                <ul className="mt-1 space-y-0.5">
                  {detail.data.outgoing.map((e) => (
                    <li key={e.id} className="text-xs">
                      <button
                        type="button"
                        className="hover:underline"
                        onClick={() => focusNode(e.target.id)}
                      >
                        {e.relation.replace(/_/g, " ")} &rarr; {e.target.name}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              Click a node to inspect and expand it.
            </p>
          )}
        </OverlayCard>
      </FullBleed>
    </AppShell>
  );
}
