import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/layout/AppShell";
import { CodeGraph } from "@/components/codegraph/CodeGraph";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { queryKeys } from "@/api/queryKeys";
import { CodeGraphNotBuiltError, getCodeGraph, getCodeGraphNode } from "@/api/codeGraph";
import type { CodeGraphParams } from "@/types/codegraph";

const LIMITS = [200, 400, 800, 1500];

/** Shown when graphify-out/ is absent - the state every fresh clone and every prod deploy is
 * in, since the artefact is gitignored on purpose. Not an error screen. */
function NotBuilt({ hint }: { hint: string }) {
  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="max-w-lg rounded-lg border bg-card p-6 text-center">
        <h2 className="text-base font-semibold">No code graph yet</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          This page renders a knowledge graph of the repository built locally by graphify. The
          output is gitignored, so it has to be generated on this machine.
        </p>
        <pre className="mt-4 overflow-x-auto rounded-md bg-muted px-3 py-2 text-left text-xs">
          {hint}
        </pre>
        <p className="mt-3 text-xs text-muted-foreground">
          Committing after that keeps it current - the post-commit hook rebuilds it.
        </p>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

const selectClass =
  "h-8 rounded-md border bg-background px-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring";

function CodeGraphPage() {
  const [search, setSearch] = useState("");
  const [searchDraft, setSearchDraft] = useState("");
  const [layer, setLayer] = useState("");
  const [module, setModule] = useState("");
  const [relation, setRelation] = useState("");
  // Verified structure first: guesses are opt-in, never the default view.
  const [showInferred, setShowInferred] = useState(false);
  const [limit, setLimit] = useState(400);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const params: CodeGraphParams = useMemo(
    () => ({
      ...(search ? { search } : {}),
      ...(layer ? { layer } : {}),
      ...(module ? { module } : {}),
      ...(relation ? { relation } : {}),
      ...(showInferred ? {} : { confidence: "EXTRACTED" }),
      limit,
    }),
    [search, layer, module, relation, showInferred, limit]
  );

  const graphQuery = useQuery({
    queryKey: queryKeys.codegraph.graph(params),
    queryFn: () => getCodeGraph(params),
    retry: false,
    placeholderData: (prev) => prev,
  });

  const detailQuery = useQuery({
    queryKey: queryKeys.codegraph.node(selectedId ?? ""),
    queryFn: () => getCodeGraphNode(selectedId as string),
    enabled: Boolean(selectedId),
    retry: false,
  });

  if (graphQuery.error instanceof CodeGraphNotBuiltError) {
    return (
      <AppShell>
        <NotBuilt hint={graphQuery.error.hint} />
      </AppShell>
    );
  }

  const data = graphQuery.data;
  const facets = data?.facets;
  const stats = data?.stats;
  const detail = detailQuery.data;

  return (
    <AppShell>
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold">Code Graph</h1>
            <p className="text-xs text-muted-foreground">
              The repository as a graph, parsed from the AST by graphify.
              {data?.built_at_commit ? ` Built at ${data.built_at_commit.slice(0, 7)}.` : ""}
            </p>
          </div>
          {stats && (
            <p className="text-xs text-muted-foreground">
              {stats.returned_nodes} of {stats.matched_nodes} matching nodes
              {stats.truncated ? " (highest-degree first)" : ""} &middot; {stats.returned_edges}{" "}
              edges &middot; {stats.total_nodes} in graph
            </p>
          )}
        </div>

        {/* Filters in one row above the chart. */}
        <div className="flex flex-wrap items-end gap-3 rounded-lg border bg-card p-3">
          <Field label="Search">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                setSearch(searchDraft.trim());
              }}
            >
              <Input
                value={searchDraft}
                onChange={(e) => setSearchDraft(e.target.value)}
                placeholder="symbol or path"
                className="h-8 w-48"
              />
            </form>
          </Field>

          <Field label="Layer">
            <select
              aria-label="Layer"
              className={selectClass}
              value={layer}
              onChange={(e) => setLayer(e.target.value)}
            >
              <option value="">All layers</option>
              {facets?.layers.map(([value, count]) => (
                <option key={value} value={value}>
                  {value} ({count})
                </option>
              ))}
            </select>
          </Field>

          <Field label="Module">
            <select
              aria-label="Module"
              className={selectClass}
              value={module}
              onChange={(e) => setModule(e.target.value)}
            >
              <option value="">All modules</option>
              {facets?.modules.slice(0, 40).map(([value, count]) => (
                <option key={value} value={value}>
                  {value} ({count})
                </option>
              ))}
            </select>
          </Field>

          <Field label="Relation">
            <select
              aria-label="Relation"
              className={selectClass}
              value={relation}
              onChange={(e) => setRelation(e.target.value)}
            >
              <option value="">All relations</option>
              {facets?.relations.map(([value, count]) => (
                <option key={value} value={value}>
                  {value} ({count})
                </option>
              ))}
            </select>
          </Field>

          <Field label="Nodes">
            <select
              aria-label="Node limit"
              className={selectClass}
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
            >
              {LIMITS.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </Field>

          <label className="flex h-8 items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={showInferred}
              onChange={(e) => setShowInferred(e.target.checked)}
            />
            <span className="text-muted-foreground">Show inferred edges</span>
          </label>

          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setSearch("");
              setSearchDraft("");
              setLayer("");
              setModule("");
              setRelation("");
              setShowInferred(false);
              setLimit(400);
              setSelectedId(null);
            }}
          >
            Reset
          </Button>
        </div>

        <div className="flex gap-4">
          <div className="relative h-[70vh] flex-1 rounded-lg border bg-card">
            {graphQuery.isLoading && (
              <p className="p-4 text-sm text-muted-foreground">Loading graph...</p>
            )}
            {graphQuery.error && !(graphQuery.error instanceof CodeGraphNotBuiltError) && (
              <p className="p-4 text-sm text-destructive">Could not load the code graph.</p>
            )}
            {data && data.nodes.length === 0 && (
              <p className="p-4 text-sm text-muted-foreground">
                No nodes match these filters.
              </p>
            )}
            {data && data.nodes.length > 0 && (
              <CodeGraph
                nodes={data.nodes}
                edges={data.edges}
                selectedId={selectedId}
                onSelect={setSelectedId}
                layoutKey={`${layer}|${module}|${relation}|${search}|${limit}`}
              />
            )}
          </div>

          <aside className="h-[70vh] w-80 shrink-0 overflow-y-auto rounded-lg border bg-card p-4">
            {!selectedId && (
              <p className="text-sm text-muted-foreground">
                Select a node to see where it lives and what connects to it.
              </p>
            )}
            {selectedId && detailQuery.isLoading && (
              <p className="text-sm text-muted-foreground">Loading...</p>
            )}
            {detail && (
              <div className="flex flex-col gap-3">
                <div>
                  <h2 className="break-words text-sm font-semibold">{detail.label}</h2>
                  <p className="mt-1 break-all font-mono text-xs text-muted-foreground">
                    {detail.file}
                    {detail.line ? `:${detail.line}` : ""}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {detail.layer} &middot; {detail.module} &middot; {detail.community_name} &middot;{" "}
                    {detail.degree} edges
                  </p>
                </div>
                <NeighbourList
                  title={`Used by (${detail.incoming.length})`}
                  items={detail.incoming}
                  onSelect={setSelectedId}
                />
                <NeighbourList
                  title={`Uses (${detail.outgoing.length})`}
                  items={detail.outgoing}
                  onSelect={setSelectedId}
                />
              </div>
            )}
          </aside>
        </div>
      </div>
    </AppShell>
  );
}

function NeighbourList({
  title,
  items,
  onSelect,
}: {
  title: string;
  items: { node: { id: string; label: string; file: string }; relation: string; confidence: string }[];
  onSelect: (id: string) => void;
}) {
  if (items.length === 0) return null;
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      <ul className="mt-1 flex flex-col gap-1">
        {items.map((item) => (
          <li key={`${item.node.id}-${item.relation}`}>
            <button
              type="button"
              onClick={() => onSelect(item.node.id)}
              className="w-full rounded px-1.5 py-1 text-left text-xs hover:bg-muted"
            >
              <span className="font-medium">{item.node.label}</span>
              <span className="text-muted-foreground">
                {" "}
                &middot; {item.relation}
                {item.confidence === "EXTRACTED" ? "" : " (inferred)"}
              </span>
              <span className="block break-all font-mono text-[10px] text-muted-foreground">
                {item.node.file}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export const Route = createFileRoute("/code-graph")({
  component: CodeGraphPage,
});
